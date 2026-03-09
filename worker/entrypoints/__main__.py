"""Allow running as: python -m worker.entrypoints"""
from worker.entrypoints.queue_worker import main

if __name__ == "__main__":
    main()
