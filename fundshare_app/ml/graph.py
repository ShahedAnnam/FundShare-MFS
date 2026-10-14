"""NetworkX-based 2-Hop Mule Ring and Transaction Flow Detection Engine."""
import logging
import threading
from decimal import Decimal

import networkx as nx
from django.utils import timezone

from fundshare_app.models import Transaction, TransactionStatus

logger = logging.getLogger(__name__)


class TransactionGraphEngine:
    """
    Engine to build and analyze transactional graph relationships for
    fan-in aggregations and 2-hop money mule pass-through rings.
    """
    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self.graph = nx.DiGraph()
        self.last_built = None
        self.default_lookback_hours = 24

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @staticmethod
    def _extract_node_id(user_or_wallet):
        """Resolves user or wallet input to a consistent integer/identifier node ID."""
        if user_or_wallet is None:
            return None
        if hasattr(user_or_wallet, 'owner_id'):  # Wallet
            return user_or_wallet.owner_id
        if hasattr(user_or_wallet, 'id'):        # User
            return user_or_wallet.id
        if isinstance(user_or_wallet, int):
            return user_or_wallet
        if isinstance(user_or_wallet, str):
            try:
                return int(user_or_wallet)
            except ValueError:
                return user_or_wallet
        return user_or_wallet

    def build_graph(self, lookback_hours=24):
        """
        Queries recent completed Transaction records from the Django ORM
        and constructs a networkx.DiGraph where nodes are user/wallet identifiers
        and directed edges represent transfers with amount and timestamp metadata.
        """
        G = nx.DiGraph()
        cutoff = timezone.now() - timezone.timedelta(hours=lookback_hours)

        txns = Transaction.objects.filter(
            status=TransactionStatus.COMPLETED,
            timestamp__gte=cutoff
        ).select_related('sender', 'receiver')

        for txn in txns:
            sender_id = txn.sender_id
            receiver_id = txn.receiver_id
            if sender_id is None or receiver_id is None:
                continue

            amount = float(txn.amount)
            ts = txn.timestamp

            if not G.has_node(sender_id):
                G.add_node(sender_id, username=txn.sender.username if txn.sender else str(sender_id))
            if not G.has_node(receiver_id):
                G.add_node(receiver_id, username=txn.receiver.username if txn.receiver else str(receiver_id))

            if G.has_edge(sender_id, receiver_id):
                edge = G[sender_id][receiver_id]
                edge['transfers'].append({'amount': amount, 'timestamp': ts})
                edge['total_amount'] += amount
                edge['count'] += 1
                if ts > edge.get('latest_timestamp', ts):
                    edge['latest_timestamp'] = ts
            else:
                G.add_edge(
                    sender_id,
                    receiver_id,
                    transfers=[{'amount': amount, 'timestamp': ts}],
                    total_amount=amount,
                    count=1,
                    latest_timestamp=ts
                )

        self.graph = G
        self.last_built = timezone.now()
        return self.graph

    def analyze_account_risk(self, user_or_wallet, current_amount=None, lookback_hours=24, rebuild=True):
        """
        Evaluates graph topology for an account:
        - Fan-in count of distinct senders over rolling lookback window (in-degree).
        - Detects 2-hop pass-through patterns: Node receives transfers from >= 3 distinct senders
          and initiates an outflow within the lookback window.

        Returns:
            dict with:
                - is_mule_suspect: bool
                - mule_boost: float (0.25 if flagged, else 0.0)
                - reasons: list of str
                - graph_metrics: dict
        """
        node_id = self._extract_node_id(user_or_wallet)
        empty_metrics = {
            'in_degree': 0,
            'out_degree': 0,
            'distinct_senders': 0,
            'distinct_receivers': 0,
            'total_fan_in_volume': 0.0,
            'total_outflow_volume': 0.0
        }

        if node_id is None:
            return {
                'is_mule_suspect': False,
                'mule_boost': 0.0,
                'reasons': [],
                'graph_metrics': empty_metrics
            }

        # Rebuild if requested or if not yet built
        if rebuild or self.graph is None or self.last_built is None:
            self.build_graph(lookback_hours=lookback_hours)

        G = self.graph
        if not G.has_node(node_id):
            return {
                'is_mule_suspect': False,
                'mule_boost': 0.0,
                'reasons': [],
                'graph_metrics': empty_metrics
            }

        # Distinct senders = in-degree
        predecessors = list(G.predecessors(node_id))
        in_degree = len(predecessors)

        total_fan_in_volume = sum(
            G[pred][node_id].get('total_amount', 0.0) for pred in predecessors
        )

        # Distinct recipients = out-degree
        successors = list(G.successors(node_id))
        out_degree = len(successors)

        total_outflow_volume = sum(
            G[node_id][succ].get('total_amount', 0.0) for succ in successors
        )

        if current_amount is not None:
            try:
                total_outflow_volume += float(current_amount)
            except (ValueError, TypeError):
                pass

        graph_metrics = {
            'in_degree': in_degree,
            'out_degree': out_degree,
            'distinct_senders': in_degree,
            'distinct_receivers': out_degree,
            'total_fan_in_volume': round(total_fan_in_volume, 2),
            'total_outflow_volume': round(total_outflow_volume, 2)
        }

        reasons = []
        is_mule_suspect = False
        mule_boost = 0.0

        # Pattern 1: High fan-in threshold (>= 3 distinct senders)
        if in_degree >= 3:
            is_mule_suspect = True
            mule_boost = 0.25
            reasons.append(f"High fan-in: {in_degree} distinct senders within {lookback_hours} hours")

            # Pattern 2: 2-hop pass-through (inflow aggregation followed by rapid outflow)
            has_outflow = out_degree > 0 or (current_amount is not None and float(current_amount) > 0)
            if has_outflow:
                reasons.append("Rapid outflow following aggregated transfers (2-hop mule ring pattern)")

        return {
            'is_mule_suspect': is_mule_suspect,
            'mule_boost': mule_boost,
            'reasons': reasons,
            'graph_metrics': graph_metrics
        }
