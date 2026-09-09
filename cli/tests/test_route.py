"""Unit tests for deterministic route navigation."""

from pauk.route import load_graph, render_route_png


def test_graph_loads():
    g = load_graph("germany-autobahn")
    assert "muenchen" in g.nodes
    assert "berlin" in g.nodes
    assert g.name_of("muenchen") == "München"


def test_moves_are_real_edges():
    g = load_graph("germany-autobahn")
    for m in g.moves("muenchen"):
        # every offered move has a positive km and is reciprocal
        assert m["km"] > 0
        assert any(back["to"] == "muenchen" for back in g.adj[m["to"]])


def test_shortest_path_is_deterministic():
    g = load_graph("germany-autobahn")
    assert g.shortest_km("muenchen", "berlin") == 595
    # same both directions (undirected graph)
    assert g.shortest_km("berlin", "muenchen") == 595


def test_route_km_validates_edges():
    g = load_graph("germany-autobahn")
    # a real consecutive path
    good = ["muenchen", "ingolstadt", "nuernberg"]
    assert g.route_km(good) == g.edge_km("muenchen", "ingolstadt") + g.edge_km(
        "ingolstadt", "nuernberg"
    )
    # a non-edge hop yields None (never silently summed)
    assert g.route_km(["muenchen", "berlin"]) is None


def test_render_produces_png():
    g = load_graph("germany-autobahn")
    png = render_route_png(g, ["muenchen", "ingolstadt", "nuernberg"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
