# Visão — identificação por reconhecimento facial

Módulo do Mini-Server que usa uma câmera **Tapo C200** para registrar quem foi identificado no
laboratório e quando (sem medir permanência), e guardar foto e vídeo de quem não é cadastrado. Tudo roda na própria TV Box
(RK322x, ARMv7, 1 GB de RAM), sem nuvem.

## Como funciona

```
Tapo C200 ──RTSP 720p──▶ ffmpeg (decodifica ~4 qps) ──▶ detector ──▶ SQLite ──▶ web :8080
          ──RTSP 1080p─▶ ffmpeg (copia, sem recodificar) ─▶ segmentos na RAM ─▶ clipes de eventos
          ──ONVIF──────▶ eventos de movimento + posição do pan/tilt
```

1. **Gatilho barato:** o detector só analisa continuamente quando a câmera avisa movimento
   (ONVIF), quando o pan/tilt está girando (a C200 segue as pessoas), quando há movimento na
   imagem ou quando há rostos sendo acompanhados. Parado, faz uma varredura a cada 20 s.
2. **Detecção:** YuNet (OpenCV) no quadro inteiro reduzido para 640×360.
3. **Qualidade:** só tenta reconhecer rostos com tamanho, nitidez e ângulo suficientes.
4. **Reconhecimento:** SFace (OpenCV) gera um vetor de 128 números por rosto, comparado com as
   amostras de cada membro. Rostos acompanhados entre ciclos não são reprocessados.
5. **Identificação:** com certeza alta (≥ 0,50) basta uma leitura; abaixo disso, duas leituras
   precisam concordar. Cada membro gera no máximo uma identificação a cada `session_gap_min`
   (30 min), para não repetir o registro enquanto a pessoa continua na sala.
6. **Desconhecidos:** várias leituras ruins e parecidas entre si viram um alerta com foto (e
   Telegram, se configurado). Rostos que não deu para decidir vão para a página **Revisão**.
7. **Aprendizado contínuo:** quando a certeza é alta, o sistema guarda novas amostras do membro
   (até 30; ao encher, troca a mais antiga), acompanhando a luz real do laboratório e mudanças
   de visual. Corrigir uma identificação errada (página Hoje → "corrigir") desfaz o que foi
   aprendido naquela identificação e ensina o rosto à pessoa certa.

Desempenho medido na TV Box: detecção ~0,6 s por quadro, reconhecimento ~0,9 s por rosto,
decodificação do 720p ~70% de um núcleo, gravação do 1080p ~20% de um núcleo.

## Proteções e manutenção

- **Proteção térmica:** acima de 78 °C a análise fica mais espaçada; acima de 85 °C, bem mais.
- **Ritmo adaptativo:** quando todos os rostos visíveis já estão identificados, analisa a cada 1,5 s;
  sem movimento, a cada 20 s.
- **Clipes em fila única:** nunca há dois ffmpeg montando vídeo ao mesmo tempo.
- **Manutenção noturna (após 03:00):** backup do banco em `data/backup/` (guarda 3 dias) e otimização.
- **Cumprimento falado:** desliga sozinho após 3 falhas seguidas, para não bloquear a conta Tapo.
- **Modo segurança (opcional, `[security]`):** movimento no horário vigiado vira alerta com foto e vídeo.

## Instalação

```bash
sudo bash visao/deploy/install.sh
sudo nano /opt/visao/config.toml      # IP e conta da câmera (app Tapo → Conta da câmera)
sudo systemctl restart visao-detector visao-web
sudo cat /root/visao-senha-inicial.txt
```

A interface fica em `http://<ip-do-servidor>:8080` (pela rede local ou pelo Tailscale).

## Uso

- **Hoje:** quem foi identificado (primeira e última vez), eventos com foto/vídeo e correção.
- **Ao vivo:** imagem da câmera com os rostos marcados e o estado do sistema.
- **Relatório:** por período, por membro (dias em que foi visto, identificações, última vez),
  horário da primeira identificação de cada dia e lista completa, com exportação para CSV.
- **Membros:** cadastro, envio de fotos e **captura pela câmera** (mais precisa: a pessoa fica
  sozinha na frente da câmera por até 90 s e o sistema guarda 12 amostras variadas).
- **Revisão:** rostos não identificados; atribuir a um membro vira nova amostra.

Linha de comando no servidor:

```bash
visao-cli status
visao-cli membros
visao-cli adicionar "Nome da Pessoa" foto1.jpg foto2.jpg
visao-cli relatorio --dias 7
visao-cli senha
```

Logs: `journalctl -u visao-detector -f`.

## Arquivos

| Caminho | Conteúdo |
| :--- | :--- |
| `/opt/visao/config.toml` | configuração (tem a senha da câmera; fora do git) |
| `/opt/visao/data/visao.db` | membros, amostras, sessões e eventos (SQLite) |
| `/opt/visao/data/members/` | fotos e recortes de rosto dos membros |
| `/opt/visao/data/events/`, `clips/` | fotos e vídeos de eventos (apagados após `retention_days`, padrão 7) |
| `/dev/shm/visao/` | imagem ao vivo, status e segmentos de vídeo (RAM) |

## Privacidade (LGPD)

Rosto é dado biométrico, ou seja, dado pessoal sensível (art. 11). Use só com membros que
deram consentimento específico para o cadastro facial. O que já existe para isso:

- os dados ficam só no servidor e a interface pede senha;
- excluir um membro apaga as fotos, as amostras e o histórico dele;
- todo o histórico (presenças, eventos, fotos, vídeos e rostos não identificados) é apagado após `retention_days` (7 dias); só as amostras de cadastro dos membros ficam.

## Limitações conhecidas

- Rostos a mais de ~5 m ficam pequenos demais no 720p.
- A C200 só segue uma pessoa por vez; com várias pessoas, ela segue o movimento.
