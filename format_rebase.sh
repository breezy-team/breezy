#!/bin/bash
# Script to run ruff format on each commit during rebase

while true; do
    # Run ruff format
    ruff format .
    
    # Check if there are any changes
    if git diff --quiet; then
        echo "No formatting changes needed for this commit"
    else
        echo "Formatting changes applied, amending commit"
        git add -A
        git commit --amend --no-edit
    fi
    
    # Continue to next commit
    if ! git rebase --continue; then
        # Check if rebase is complete
        if git status | grep -q "No rebase in progress"; then
            echo "Rebase completed successfully!"
            break
        else
            echo "Rebase conflict or error occurred"
            exit 1
        fi
    fi
    
    # Check if we're still in rebase mode
    if ! git status | grep -q "interactive rebase in progress"; then
        echo "Rebase completed!"
        break
    fi
done