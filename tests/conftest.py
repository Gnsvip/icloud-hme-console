"""Provide an isolated, non-production password for tests only."""
import os

os.environ.setdefault('ADMIN_PASSWORD', 'test-only-not-for-deployment')
