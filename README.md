# Mini-Server: MXQ Pro 4K 5G Headless Server

Transformação de TV Box baseadas em SoC ARM (Rockchip RK322x, Amlogic S905x ou Allwinner H3) em servidor doméstico autônomo 24/7 com consumo reduzido (~3W): bloqueador de anúncios em rede, NAS, VPN e **Visão**, um sistema de identificação por reconhecimento facial com uma câmera Tapo C200, que roda inteiro na TV Box, sem nuvem.

[![OS: Armbian Minimal](https://img.shields.io/badge/OS-Armbian%20Debian%20Trixie-red.svg)](https://www.armbian.com/)
[![Architecture: ARM](https://img.shields.io/badge/Architecture-ARMv7%20%2F%20ARM64-blue.svg)](https://github.com/VituColombo0/Mini-Server)
[![DNS: AdGuard Home](https://img.shields.io/badge/DNS-AdGuard%20Home-success.svg)](https://adguard.com/adguard-home.html)
[![Visão: OpenCV](https://img.shields.io/badge/Vis%C3%A3o-OpenCV%20YuNet%20%2B%20SFace-5C3EE8.svg)](visao/README.md)
[![Mesh VPN: Tailscale](https://img.shields.io/badge/VPN-Tailscale-black.svg)](https://tailscale.com/)

---

## Especificações do Hardware (Unidade Atual)

Configuração extraída diretamente do hardware em produção:

| Componente | Especificação |
| :--- | :--- |
| **Dispositivo** | TV Box MXQ Pro 4K 5G (Placa: Generic RK322x Board) |
| **SoC / Processador** | Rockchip RK322x — Quad-Core ARM Cortex-A7 (ARMv7l 32-bit) |
| **Frequência da CPU** | 600 MHz a 1.20 GHz (Governor dinâmico térmico) |
| **Memória RAM** | 1 GB DDR3 (~970 MB acessíveis pelo kernel) |
| **Swap / ZRAM** | 485 MB comprimido via ZRAM (lz4) |
| **Armazenamento Interno** | 8 GB eMMC Flash (~7.3 GB utilizáveis em `/dev/mmcblk2`) |
| **Rede** | Ethernet Fast Ethernet (10/100 Mbps) + Wi-Fi integrado |
| **Portas de Expansão** | 4x USB 2.0 + 1x Leitor de Cartão SD/MMC |
| **Consumo Elétrico** | ~2.5W a 4.5W (Fonte 5V / 2A) |
| **Sistema Operacional** | Armbian Linux (Debian Trixie) |
| **Kernel** | Linux 6.18.60-current-rockchip (LTS moderno com patches RK322x) |

---

## Arquitetura de Serviços

O sistema disponibiliza uma suíte integrada de utilitários de infraestrutura local:

```
┌─────────────────────────────────────────────────────────────┐
│                    TV Box MXQ Pro 4K                        │
│             Armbian Minimal (Linux Kernel LTS)              │
├─────────────────────────────────────────────────────────────┤
│  [ AdGuard Home :3000 ]  ── Bloqueio de anúncios por DNS    │
│  [ FileBrowser :8082 ]   ── Gerenciador web de arquivos     │
│  [ Samba / SMB :445 ]    ── Compartilhamento de rede local  │
│  [ SSH Direto :22 ]      ── Acesso seguro por chave Ed25519 │
│  [ Tailscale VPN ]       ── Conexão remota externa segura   │
├─────────────────────────────────────────────────────────────┤
│  Visão (reconhecimento facial — câmera Tapo C200)           │
│  [ visao-web :8080 ]     ── Painel: hoje, relatório, membros│
│  [ visao-detector ]      ── Detecção, identificação, clipes │
│  [ visao-go2rtc ]        ── Áudio para a câmera (só local)  │
└─────────────────────────────────────────────────────────────┘
```

> O Docker vem instalado pelo setup, mas fica **desativado** (sem contêineres) para liberar ~100 MB de RAM e CPU para o Visão. Para religar: `sudo systemctl enable --now docker`.

### Otimizações de Kernel e Resiliência de Hardware

A configuração inclui ajustes específicos para contornar limitações de memória e prolongar a durabilidade dos componentes:
- **ZRAM com Compressão LZ4:** Expande a memória RAM efetiva em até 60% por meio de compressão rápida em bloco, prevenindo *Out-Of-Memory* (OOM) em placas com 1GB de RAM.
- **Proteção do Armazenamento (Flash Wear Leveling):** Montagem do sistema com flags `noatime`, `nodiratime` e `commit=60`. O buffer do `systemd-journald` opera em memória volátil (`volatile`), reduzindo o ciclo contínuo de escritas em memórias MicroSD e eMMC baratas.
- **Governor de CPU Térmico:** Configuração dos governors `schedutil` ou `ondemand` para adequação dinâmica de clock, assegurando operação estável sem superaquecimento mesmo em gabinetes passivos sem cooler.
- **Hardware Watchdog:** Módulo de kernel ativo para forçar reinicialização automática do hardware caso ocorra congelamento de kernel ou microquedas de tensão.
- **Prevenção de Ataques (Fail2ban):** Bloqueio progressivo de endereços IP após tentativas repetidas de força bruta no SSH e nos serviços HTTP.
- **Manutenção Automatizada:** Rotinas no `cron` para descarte de cache de pacotes APT; o Visão faz backup noturno do próprio banco e apaga histórico com mais de 7 dias.
- **Proteção Térmica do Visão:** acima de 78 °C a análise de vídeo fica mais espaçada (85 °C: bem mais), para a TV Box não superaquecer nem travar.

---

## Modos de Instalação

### Instalação Headless (Sem TV, Sem Teclado e Sem Controle)

O processo de instalação automatizado roda a partir do cartão MicroSD sem necessidade de monitor ou teclado conectado à TV Box.

#### 1. Gravação da Imagem Base
1. Baixe o **Armbian Minimal (CLI)** correspondente ao processador da sua placa (ex.: RK322x, S905x ou H3).
2. Grave o arquivo `.img` em um cartão MicroSD (TF Card) Classe 10 ou A1 através do [balenaEtcher](https://etcher.balena.io/) ou [Rufus](https://rufus.ie/).

#### 2. Preparação do Cartão no Computador Host
No computador com Linux ou WSL, monte a partição raiz (`rootfs`) do cartão e aplique o script de inicialização autônoma:

```bash
git clone https://github.com/VituColombo0/Mini-Server.git
cd Mini-Server
sudo chmod +x *.sh

# Definindo usuário e senha (recomendado: use uma senha própria e forte):
sudo ./prepare_sd_card.sh /media/$USER/armbi_root usuario SENHA_FORTE
```
*(Substitua `/media/$USER/armbi_root` pelo ponto de montagem real da partição no seu sistema).*

#### 3. Inicialização e Provisionamento
1. Insira o MicroSD na TV Box.
2. Conecte o cabo de rede Ethernet ao roteador.
3. Conecte a fonte de alimentação na tomada.
4. O serviço `mxq-bootstrap` efetuará a requisição DHCP, instalará os pacotes e configurará os serviços em segundo plano (processo dura entre 10 e 15 minutos).

---

## Mapeamento de Portas e Credenciais de Acesso

Ao término do provisionamento, todos os serviços estarão acessíveis na rede local via endereço IP atribuído ou mDNS (`mxq-server.local`):

### Painéis de Usuário

| Serviço | Porta / URL | Usuário Padrão | Finalidade |
| :--- | :--- | :--- | :--- |
| **AdGuard Home** | `http://<IP>:3000` | Definido no 1º login | Bloqueador de anúncios e filtros de rede |
| **FileBrowser Web** | `http://<IP>:8082` | definido na instalação | Nuvem pessoal de arquivos e mídias USB |
| **Samba (NAS)** | `\\<IP>\Compartilhado` | definido na instalação | Compartilhamento SMB para Windows/Mac/Linux |
| **Visão (painel)** | `http://<IP>:8080` | definido com `visao-cli senha` | Quem foi identificado, relatórios, membros, revisão |

### Acesso Administrativo e Manutenção Remota

| Recurso | Método de Acesso | Credenciais | Operação |
| :--- | :--- | :--- | :--- |
| **Editor de Arquivos Root** | `http://<IP>:8082` | usuário administrador | Edição de arquivos do sistema (`/etc`, `/boot`) |
| **Acesso SSH (Senha)** | `ssh <usuario>@<IP>` (porta 22) | usuário administrador | Sessão remota com permissão sudo total |
| **Acesso SSH (Chave)** | `ssh miniserver` (porta 22) | Chave `id_ed25519` autorizada | Login automático direto sem senha |
| **Atualização OTA** | Comando `mxq-update` | Terminal / SSH | Sincronização direta com o repositório GitHub |
| **Rede Remota (VPN)** | `sudo tailscale up --accept-dns=false` | Conta Pessoal Tailscale | Acesso de fora da LAN sem expor portas |

> As senhas **não ficam neste repositório**. Um registro completo com links e senhas é gerado no próprio dispositivo em `/root/server-credentials.txt` (`chmod 600`). As credenciais da câmera ficam em `/opt/visao/config.toml` (`root:visao`, `640`).

### 🔑 Configuração do Acesso SSH por Chaves e Tailscale

Para aplicar as chaves SSH autorizadas e ativar o acesso remoto:
```bash
# 1. Puxe as atualizações mais recentes do repositório
cd /root/Mini-Server
git pull origin main

# 2. Execute o configurador de SSH para autorizar as chaves
sudo ./scripts/setup_ssh.sh

# 3. (Opcional, recomendado) Ativar acesso remoto seguro via Tailscale VPN
sudo tailscale up --ssh
```

---

## Visão: identificação por reconhecimento facial

> **Evolução:** o Visão segue agora no repositório **[Willbert](https://github.com/VituColombo0/Willbert)**,
> rodando num PC (tempo real, modelo de linguagem local, conversa por voz). A versão daqui
> continua mantida como **reserva**: se o PC cair, a TV Box assume; ela também grava os
> clipes, vigia o PC e guarda backup dos cadastros.


Módulo em [`visao/`](visao/README.md) que usa uma câmera **Tapo C200** (RTSP + ONVIF) para registrar
**quem foi identificado no laboratório e quando**, com foto e vídeo. Tudo roda na própria TV Box.

- **Detecção e reconhecimento:** OpenCV (YuNet + SFace), com a wheel ARMv7 com NEON do piwheels. O pacote do Debian não tem NEON e é 2–4× mais lento.
- **Gatilho barato:** a análise contínua só liga com movimento (evento ONVIF da câmera, pan/tilt girando ou mudança na imagem); parado, faz uma varredura a cada 20 s.
- **Menos erros:** confirmação por duas leituras, aprendizado contínuo de amostras e botão "corrigir" que desfaz o que foi aprendido errado.
- **Pessoas sem cadastro:** alerta "desconhecido" e página de revisão, sempre com foto e vídeo de ~30 s em 1080p.
- **Cumprimento falado:** "Bom dia, Nome!" na primeira identificação do dia, com voz offline (espeak-ng + MBROLA pt-BR), pela câmera (go2rtc) ou pela saída de som da TV Box.
- **Privacidade:** histórico, fotos e vídeos são apagados após 7 dias; só ficam as amostras de cadastro dos membros.

Instalação: `sudo bash visao/deploy/install.sh`. Detalhes, configuração e linha de comando (`visao-cli`) estão em [`visao/README.md`](visao/README.md).

---

## Armazenamento: MicroSD vs Memória Interna (eMMC/NAND)

### Opção 1: Operação Contínua via MicroSD (Recomendado)
- **Vantagem:** Inexistência de risco de inutilização (*brick*) da placa. Para restaurar o sistema Android original, basta remover o cartão e reiniciar o dispositivo.
- **Performance:** Cartões modernos de padrão A1/A2 oferecem taxas de leitura randômica superiores aos chips eMMC legados que equipam TV Boxes genéricas.

### Opção 2: Gravação na Memória Flash Interna
Se houver preferência por liberar o slot MicroSD após o término da configuração:
1. Conecte-se ao terminal web ou SSH e execute:
   ```bash
   sudo mxq-install-internal
   ```
2. O script identifica o subsistema correspondente (`armbian-install`, `install-aml.sh` ou `nand-sata-install`), formata a partição eMMC interna e migra os binários e o bootloader.
3. Desligue o dispositivo (`sudo poweroff`), retire o cartão MicroSD e religue na tomada.
*(Em chips Rockchip RK322x, o procedimento também pode ser realizado com o Rockchip Multitool selecionando "Burn image to eMMC/NAND").*

---

## Métricas de Consumo de Recursos

Medições práticas em operação estável sob o Armbian Minimal:

| Serviço / Componente | Consumo Real de RAM | Uso Médio de CPU em Repouso |
| :--- | :--- | :--- |
| **Armbian Minimal (Base)** | ~60 MB | < 1.0% |
| **AdGuard Home** | ~35 MB | < 0.5% |
| **FileBrowser Web** | ~15 MB | < 0.2% |
| **Serviço Samba (SMB)** | ~20 MB | < 0.5% |
| **Tailscale / SSH** | ~20 MB | < 0.2% |
| **Visão: detector** (Python + OpenCV) | ~150 MB | ~6% (parado), até ~60% com movimento |
| **Visão: decodificação do vídeo 720p** (ffmpeg) | ~55 MB | ~23% (≈ 1 núcleo de 4) |
| **Visão: gravação em anel 1080p** (ffmpeg, cópia) | ~40 MB | ~2% |
| **Visão: painel web + go2rtc** | ~70 MB | < 1% |
| **Total Estimado** | **~500 MB de RAM** | **~30% de CPU parado** |

> Medido na unidade atual (RK322x, 1 GB). Com o Visão parado, a TV Box fica ~68% ociosa e a ~66 °C.

---

## Configuração do DNS no Roteador

Para estender a filtragem de anúncios e telemetria a todos os dispositivos conectados à rede doméstica:
1. Acesse o painel de administração do seu roteador (frequentemente em `192.168.1.1` ou `192.168.0.1`).
2. Localize a seção **DHCP / Configurações de DNS**.
3. Defina o **DNS Primário (IPv4)** com o endereço IP fixo atribuído à TV Box.
4. Reinicie a conexão dos clientes para que recebam a nova tabela DHCP.

---

## Estrutura do Repositório

```text
Mini-Server/
├── autorun-headless.sh          # Script de execução autônoma pós-boot
├── configure_adguard_lists.sh   # Configuração de listas de bloqueio e filtros
├── prepare_sd_card.sh           # Utilitário para gravação e injeção do bootstrap no host
├── setup_mxq_server.sh          # Script mestre de provisionamento de serviços e kernel
├── systemd/                     # Unidades de serviço para inicialização
├── visao/                       # Reconhecimento facial com a Tapo C200 (ver visao/README.md)
│   ├── visao/                   # Código Python (detector, web, CLI, câmera, rostos)
│   ├── deploy/                  # install.sh e unidades systemd do Visão
│   └── config.example.toml      # Modelo de configuração (a real fica fora do git)
├── docs/                        # Documentações adicionais de suporte e pinouts
└── README.md                    # Documentação técnica do projeto
```

---

## Licença

Projeto desenvolvido para reaproveitamento de hardware e automação residencial. Código aberto para uso pessoal e comunitário.
