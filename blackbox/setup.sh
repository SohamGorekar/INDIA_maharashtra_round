#!/bin/bash

echo "=== Black Box SDK Setup ==="
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Create virtual environment (optional)
read -p "Create virtual environment? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Virtual environment activated"
fi

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install -e .

# Check installation
echo ""
echo "Verifying installation..."
python3 -c "from blackbox import trace, BlackBoxContext; print('✅ Black Box SDK imported successfully')"

# Run quickstart
echo ""
read -p "Run quickstart example? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo "Running quickstart..."
    python3 examples/quickstart.py
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Try: python examples/customer_support/agent.py"
echo "  2. Start API: uvicorn blackbox.api.app:app --reload"
echo "  3. Read docs: docs/integration.md"
echo ""
