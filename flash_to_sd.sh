#!/bin/bash
# ==============================================================================
# Script de Gravação Automática do Multitool + Armbian no Cartão SD
# Dispositivo alvo: /dev/sdc (Cartão MicroSD de 8GB)
# ==============================================================================

set -euo pipefail

TARGET_DEV="${1:-/dev/sdc}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MULTITOOL_XZ="${PROJECT_DIR}/downloads/multitool.img.xz"
ARMBIAN_IMG="${PROJECT_DIR}/downloads/Armbian_rk322x-box_trixie_minimal.img"
ARMBIAN_XZ="${PROJECT_DIR}/downloads/Armbian_rk322x-box_trixie_minimal.img.xz"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Erro: Este script precisa ser executado com permissões de root (sudo).${NC}"
    echo -e "Execute: ${CYAN}sudo $0${NC}"
    exit 1
fi

if [ ! -b "$TARGET_DEV" ]; then
    echo -e "${RED}Erro: Dispositivo $TARGET_DEV não encontrado!${NC}"
    echo "Verifique com 'lsblk' qual é a letra do seu cartão MicroSD."
    exit 1
fi

echo -e "${CYAN}${BOLD}======================================================================${NC}"
echo -e "${CYAN}${BOLD}  Gravador Automático: Multitool RK322x + Armbian Linux              ${NC}"
echo -e "${CYAN}${BOLD}  Alvo: ${TARGET_DEV}                                                ${NC}"
echo -e "${CYAN}${BOLD}======================================================================${NC}"

echo -e "\n${YELLOW}⚠️  ATENÇÃO: O dispositivo ${TARGET_DEV} será formatado!${NC}"
echo -e "O backup dos seus arquivos do Cardputer já está salvo e protegido em:"
echo -e "👉 ${GREEN}/home/lirool/Backup_SD_Cardputer${NC}"
echo -e "👉 ${GREEN}/home/lirool/Backup_SD_Cardputer.tar.gz${NC}\n"

# 1. Desmontar partições ativas
echo -e "${CYAN}[1/5] Desmontando partições ativas de ${TARGET_DEV}...${NC}"
for part in $(lsblk -ln -o NAME "${TARGET_DEV}" | tail -n +2); do
    umount -l "/dev/${part}" 2>/dev/null || true
done

# 2. Gravar Multitool no SD
echo -e "${CYAN}[2/5] Gravando Multitool no cartão ${TARGET_DEV}...${NC}"
xzcat "${MULTITOOL_XZ}" | dd of="${TARGET_DEV}" bs=4M status=progress conv=fsync

echo -e "${CYAN}[3/5] Atualizando tabela de partições...${NC}"
sync
partprobe "${TARGET_DEV}" 2>/dev/null || true
sleep 3

# 3. Identificar partição de dados do Multitool
# No Multitool a partição 1 é a partição de dados (NTFS/FAT32 com label ou tipo data)
MOUNT_POINT="/mnt/multitool_images"
mkdir -p "${MOUNT_POINT}"

# Tenta montar sdc1 ou a maior partição
DATA_PART="${TARGET_DEV}1"
if [ ! -b "${DATA_PART}" ]; then
    DATA_PART="${TARGET_DEV}p1"
fi

echo -e "${CYAN}[4/5] Montando partição de dados (${DATA_PART})...${NC}"
mount "${DATA_PART}" "${MOUNT_POINT}" || mount -t ntfs-3g "${DATA_PART}" "${MOUNT_POINT}" || mount -t vfat "${DATA_PART}" "${MOUNT_POINT}"

# 4. Copiar Armbian e scripts para a pasta /images/
echo -e "${CYAN}[5/5] Copiando imagem do Armbian e arquivos de instalação...${NC}"
mkdir -p "${MOUNT_POINT}/images"
mkdir -p "${MOUNT_POINT}/Mini-Server"

if [ -f "${ARMBIAN_IMG}" ]; then
    echo "Copiando imagem Armbian descompactada (.img) para /images/..."
    cp -v "${ARMBIAN_IMG}" "${MOUNT_POINT}/images/"
elif [ -f "${ARMBIAN_XZ}" ]; then
    echo "Copiando imagem Armbian (.img.xz) para /images/..."
    cp -v "${ARMBIAN_XZ}" "${MOUNT_POINT}/images/"
fi

# Copiar os scripts do Mini-Server para fácil acesso
cp -r "${PROJECT_DIR}"/* "${MOUNT_POINT}/Mini-Server/" 2>/dev/null || true

sync
umount "${MOUNT_POINT}"
rmdir "${MOUNT_POINT}" 2>/dev/null || true

echo ""
echo -e "${GREEN}${BOLD}======================================================================${NC}"
echo -e "${GREEN}${BOLD}  ✅ SUCESSO! Cartão MicroSD gravado e pronto para a MXQ Pro!         ${NC}"
echo -e "${GREEN}${BOLD}======================================================================${NC}"
echo ""
echo -e "Passo a passo na sua MXQ Pro 4K 5G:"
echo -e "  1. Retire o cartão MicroSD do computador e insira na TV Box."
echo -e "  2. Conecte o cabo HDMI na TV e conecte um teclado USB na TV Box."
echo -e "  3. Ligue a TV Box na fonte (se não der vídeo de primeira, ligue segurando"
echo -e "     o botão reset dentro da entrada AV com um palito por 5 segundos)."
echo -e "  4. O menu do Multitool vai aparecer na tela!"
echo -e "     - Escolha: 'Backup flash' (opcional, para guardar a ROM antiga de fábrica)."
echo -e "     - Escolha: 'Burn image to flash' -> selecione a imagem do Armbian."
echo -e "     - Confirme a gravação na memória interna (eMMC)."
echo -e "  5. Assim que terminar: DESLIGUE a TV Box e RETIRE O MICROSD!"
echo -e "  6. Conecte o cabo de rede Ethernet e ligue a TV Box na tomada."
echo -e "  7. Ela dará boot 100% pela memória interna eMMC!"
echo ""
