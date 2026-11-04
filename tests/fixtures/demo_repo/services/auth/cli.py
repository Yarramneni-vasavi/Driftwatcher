"""Auth CLI with a --dry-run flag."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(args)


if __name__ == "__main__":
    main()
