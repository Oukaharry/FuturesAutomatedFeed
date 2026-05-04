#!/usr/bin/env python
"""Filter script to remove Cursor co-author from commit messages"""
import sys

# Read the commit message from stdin
message = sys.stdin.read()

# Remove the Cursor co-author line
lines = message.split('\n')
filtered_lines = [line for line in lines if 'Co-authored-by: Cursor <cursoragent@cursor.com>' not in line]
filtered_message = '\n'.join(filtered_lines)

# Write the filtered message back to stdout
sys.stdout.write(filtered_message)
