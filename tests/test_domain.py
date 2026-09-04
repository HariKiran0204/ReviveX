from recoverai_domain import PHASE, __version__


def test_domain_version() -> None:
    assert __version__ == "0.1.0"
    assert PHASE == 8
