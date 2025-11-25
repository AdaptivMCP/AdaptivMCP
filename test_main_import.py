def test_import_main():
    import main
    assert hasattr(main, "app")
