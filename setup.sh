#!/bin/bash
set -e

echo "=== AussieInvest Setup ==="

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose..."
    apt-get update && apt-get install -y docker-compose-plugin
fi

# Create .env if missing
if [ ! -f .env ]; then
    cp .env.example .env
    DB_PW=$(openssl rand -hex 16)
    SECRET=$(openssl rand -hex 32)
    sed -i "s/CHANGE_ME_secure_password_here/$DB_PW/" .env
    sed -i "s/CHANGE_ME_generate_with_openssl/$SECRET/" .env
    echo "Created .env with generated secrets"
fi

# Start
echo "Starting containers..."
docker compose up -d --build

echo ""
echo "=== AussieInvest is running! ==="
echo "Open: http://$(hostname -I | awk '{print $1}')"
echo "API:  http://$(hostname -I | awk '{print $1}')/api/health"
echo ""
echo "Next: Create your user:"
echo "  curl -X POST http://localhost/api/auth/register -H 'Content-Type: application/json' -d '{\"username\":\"klaus\",\"password\":\"YOUR_PASSWORD\"}'"
