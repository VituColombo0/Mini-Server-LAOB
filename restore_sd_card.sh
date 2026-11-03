#!/bin/bash
# ==============================================================================
# Script para Restaurar o Cartão SD do Cardputer (Bruce M5Stack)
# ==============================================================================

set -euo pipefail

TARGET_DEV="${1:-/dev/sdc}"
BACKUP_DIR="/home/lirool/Backup_SD_Cardputer"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Erro: Execute este script com sudo: sudo $0${NC}"
    exit 1
fi

if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${RED}Erro: Pasta de backup $BACKUP_DIR não encontrada!${NC}"
    exit 1
fi

if [ ! -b "$TARGET_DEV" ]; then
    echo -e "${RED}Erro: Dispositivo $TARGET_DEV não encontrado!${NC}"
    exit 1
fi

echo -e "${CYAN}${BOLD}======================================================================${NC}"
echo -e "${CYAN}${BOLD}  Restaurando Cartão MicroSD para o Cardputer (M5Stack / Bruce)       ${NC}"
echo -e "${CYAN}${BOLD}======================================================================${NC}"

# Desmontar
for part in $(lsblk -ln -o NAME "${TARGET_DEV}" | tail -n +2); do
    umount -l "/dev/${part}" 2>/dev/null || true
done

# Criar partição FAT32 única
echo -e "${CYAN}[1/3] Formatando cartão em FAT32 com label CARDPUTER...${NC}"
parted -s "${TARGET_DEV}" mklabel msdos
parted -s "${TARGET_DEV}" mkpart primary fat32 1MiB 100%
sleep 2

PART="${TARGET_DEV}1"
if [ ! -b "$PART" ]; then
    PART="${TARGET_DEV}p1"
fi

mkfs.vfat -F 32 -n "CARDPUTER" "$PART"

MOUNT_DIR="/mnt/restore_cardputer"
mkdir -p "$MOUNT_DIR"
mount "$PART" "$MOUNT_DIR"

echo -e "${CYAN}[2/3] Restaurando todos os arquivos originais do backup...${NC}"
rsync -avh "${BACKUP_DIR}/" "${MOUNT_DIR}/"

echo -e "${CYAN}[3/3] Sincronizando com o cartão...${NC}"
sync
umount "$MOUNT_DIR"
rmdir "$MOUNT_DIR" 2>/dev/null || true

echo ""
echo -e "${GREEN}${BOLD}======================================================================${NC}"
echo -e "${GREEN}${BOLD}  ✅ Cartão restaurado com 100% de sucesso para o Cardputer!         ${NC}"
echo -e "${GREEN}${BOLD}======================================================================${NC}"
echo "Todos os seus arquivos originais do Bruce, credenciais, pcap e firmwares voltaram."
echo ""
