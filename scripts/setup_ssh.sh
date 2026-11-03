#!/bin/bash
# ==============================================================================
# Script de Configuração Rápida de Acesso SSH e Chaves Remotas
# Projeto: Mini-Server MXQ Pro 4K 5G
#
# Uso:
#   sudo ./scripts/setup_ssh.sh
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}❌ Erro: Este script precisa ser executado como root (use sudo).${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
AUTH_KEYS_FILE="${PROJECT_DIR}/config/authorized_keys"

echo -e "${CYAN}${BOLD}====================================================================${NC}"
echo -e "${CYAN}${BOLD}  🔑 CONFIGURAÇÃO DE CHAVES SSH E ACESSO REMOTO — MINI-SERVER       ${NC}"
echo -e "${CYAN}${BOLD}====================================================================${NC}"

if [ ! -f "${AUTH_KEYS_FILE}" ]; then
    echo -e "${RED}❌ Arquivo de chaves não encontrado em: ${AUTH_KEYS_FILE}${NC}"
    exit 1
fi

install_keys_for_user() {
    local USER_NAME="$1"
    local USER_HOME
    USER_HOME=$(eval echo "~${USER_NAME}")

    if ! id "${USER_NAME}" &>/dev/null; then
        return 0
    fi

    echo -e "${GREEN}➡️  Instalando chaves autorizadas para o usuário '${USER_NAME}'...${NC}"
    mkdir -p "${USER_HOME}/.ssh"
    touch "${USER_HOME}/.ssh/authorized_keys"

    local added=0
    while IFS= read -r key || [ -n "$key" ]; do
        [[ -z "$key" || "$key" =~ ^# ]] && continue
        if ! grep -q -F "$key" "${USER_HOME}/.ssh/authorized_keys"; then
            echo "$key" >> "${USER_HOME}/.ssh/authorized_keys"
            echo "   [+] Adicionada: $(echo "$key" | awk '{print $3}')"
            added=$((added + 1))
        fi
    done < "${AUTH_KEYS_FILE}"

    chmod 700 "${USER_HOME}/.ssh"
    chmod 600 "${USER_HOME}/.ssh/authorized_keys"
    chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}/.ssh"

    if [ "$added" -eq 0 ]; then
        echo "   [i] Nenhuma chave nova necessária (todas já autorizadas)."
    fi
}

# 1. Instalar para root, Lirool e usuários locais
install_keys_for_user "root"
install_keys_for_user "Lirool"
if id "vimora" &>/dev/null; then
    install_keys_for_user "vimora"
fi

# 2. Assegurar configuração correta no daemon SSH
SSHD_CONFIG="/etc/ssh/sshd_config"
if [ -f "$SSHD_CONFIG" ]; then
    sed -i -E 's/^#?PubkeyAuthentication .*/PubkeyAuthentication yes/' "$SSHD_CONFIG"
    sed -i -E 's/^#?AuthorizedKeysFile .*/AuthorizedKeysFile .ssh\/authorized_keys/' "$SSHD_CONFIG"
fi

if [ -d "/etc/ssh/sshd_config.d" ]; then
    cat > /etc/ssh/sshd_config.d/99-miniserver-keys.conf << 'EOF'
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
EOF
fi

# 3. Reiniciar serviço SSH
if systemctl is-active --quiet ssh 2>/dev/null || systemctl is-enabled --quiet ssh 2>/dev/null; then
    systemctl restart ssh 2>/dev/null || true
elif systemctl is-active --quiet sshd 2>/dev/null || systemctl is-enabled --quiet sshd 2>/dev/null; then
    systemctl restart sshd 2>/dev/null || true
fi

# 4. Exibir IPs e comandos prontos para conexão
LOCAL_IPS=$(hostname -I 2>/dev/null || true)
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || true)

echo ""
echo -e "${GREEN}${BOLD}====================================================================${NC}"
echo -e "${GREEN}${BOLD}  🎉 SSH CONFIGURADO COM SUCESSO! CHAVES AUTORIZADAS!               ${NC}"
echo -e "${GREEN}${BOLD}====================================================================${NC}"
echo -e "Endereços IP detectados:"
echo -e "  📡 Rede Local (LAN):  ${CYAN}${LOCAL_IPS}${NC}"
if [ -n "$TAILSCALE_IP" ]; then
    echo -e "  🌐 Tailscale VPN:     ${CYAN}${TAILSCALE_IP}${NC}"
fi

FIRST_IP=$(echo "$LOCAL_IPS" | awk '{print $1}')
echo ""
echo -e "Comandos para conectar a partir do PC / Antigravity:"
echo -e "  ${YELLOW}ssh Lirool@${FIRST_IP:-mxq-server.local}${NC}"
echo -e "  ${YELLOW}ssh root@${FIRST_IP:-mxq-server.local}${NC}"
echo -e "  (Ou simplesmente: ${YELLOW}ssh miniserver${NC} se usar o alias configurado)"

if [ -z "$TAILSCALE_IP" ]; then
    echo ""
    echo -e "${YELLOW}Dica: Para habilitar acesso de FORA DE CASA sem abrir portas no roteador:${NC}"
    echo -e "  Execute: ${CYAN}sudo tailscale up --ssh${NC}"
fi
echo -e "${GREEN}${BOLD}====================================================================${NC}"
