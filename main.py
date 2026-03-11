#!/usr/bin/env python3
"""
Run:
    uvicorn main:app --reload
"""

from app.app import create_app

app = create_app()
