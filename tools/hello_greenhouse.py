#!/usr/bin/env python3
"""A trivial seed utility so the sandbox repo isn't empty — gives spikes a real surface to extend."""
def greet(name: str = "Ace") -> str:
    return f"greenhouse-sandbox is live, {name}."

if __name__ == "__main__":
    print(greet())
