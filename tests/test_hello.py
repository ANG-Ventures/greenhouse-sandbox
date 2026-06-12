from tools.hello_greenhouse import greet
def test_greet_default():
    assert "greenhouse-sandbox is live" in greet()
def test_greet_name():
    assert greet("X").endswith("X.")
