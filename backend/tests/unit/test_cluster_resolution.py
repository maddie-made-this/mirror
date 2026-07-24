"""
Louvain resolution scaling.

The property under test: cluster GRANULARITY should stay roughly constant as a
user's graph grows. Modularity has a resolution limit — at fixed resolution the
smallest detectable community grows with the graph — which showed up as distinct
concepts being subsumed into ever-broader themes the longer someone talked.
"""
import networkx as nx
from networkx.algorithms.community import louvain_communities

from config.loader import APP_CONFIG
from services.clustering import _RESOLUTION_PIVOT_NODES, _resolution_for


def test_small_graphs_use_the_configured_resolution():
    assert _resolution_for(4) == APP_CONFIG.cluster_resolution
    assert _resolution_for(_RESOLUTION_PIVOT_NODES) == APP_CONFIG.cluster_resolution


def test_resolution_rises_with_graph_size():
    """The core fix: a bigger graph gets a higher resolution, which favours more
    and smaller communities, cancelling the resolution limit."""
    small = _resolution_for(_RESOLUTION_PIVOT_NODES)
    mid = _resolution_for(_RESOLUTION_PIVOT_NODES * 4)
    large = _resolution_for(_RESOLUTION_PIVOT_NODES * 16)
    assert small < mid < large


def test_resolution_is_capped():
    """Unbounded scaling would shatter a large graph into singletons, which is as
    useless as one giant blob."""
    assert _resolution_for(500_000) == APP_CONFIG.cluster_resolution_max
    assert _resolution_for(10_000) <= APP_CONFIG.cluster_resolution_max


def test_default_resolution_is_above_one():
    """1.0 (the library default) is what produced the over-merging; the whole
    point of the knob is to sit above it."""
    assert APP_CONFIG.cluster_resolution > 1.0


def test_higher_resolution_yields_more_communities_on_a_barbell():
    """End-to-end sanity on a graph with obvious sub-structure: two dense cliques
    joined by a single bridge, times two. Raising resolution must not REDUCE the
    community count."""
    g = nx.Graph()
    for base in (0, 10, 20, 30):
        members = range(base, base + 5)
        for a in members:
            for b in members:
                if a < b:
                    g.add_edge(a, b, weight=1.0)
    # thin bridges between the cliques
    g.add_edge(4, 10, weight=0.1)
    g.add_edge(14, 20, weight=0.1)
    g.add_edge(24, 30, weight=0.1)

    low = len(louvain_communities(g, weight="weight", seed=42, resolution=0.5))
    high = len(louvain_communities(g, weight="weight", seed=42, resolution=2.0))
    assert high >= low
