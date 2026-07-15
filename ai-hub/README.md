# AI Hub — central de agentes de IA

Um painel web para hospedar vários agentes de IA (os que você já configurou com
a NVIDIA e outros que você queira adicionar depois), cada um em sua própria
coluna de conversa, todos utilizáveis ao mesmo tempo, com login multiusuário,
histórico salvo em banco de dados e uma **Ponte** que faz dois ou mais agentes
conversarem entre si.

## O que vem pronto

- **4 agentes pré-configurados** a partir dos scripts que você enviou: GLM-5.2,
  Step-3.7 Flash, MiniMax M3 e Mistral Medium 3.5 (todos via
  `integrate.api.nvidia.com`).
- **Login e cadastro** com senha criptografada (bcrypt). O primeiro usuário
  criado vira administrador automaticamente.
- **Banco de dados SQLite** (`backend/app_data.db`, criado sozinho no primeiro
  uso) guardando usuários, sessões, agentes e todo o histórico de conversas —
  cada usuário só vê as próprias conversas.
- **Colunas simultâneas**: abra quantos agentes quiser lado a lado (ou empilhados
  no celular) e converse com cada um independentemente.
- **Ponte multi-IA**: escolha 2 ou mais agentes, dê um tópico, e eles conversam
  entre si por várias rodadas — cada um vendo o que os outros (e você) disseram.
- **Streaming** das respostas em tempo real, com exibição separada do
  "raciocínio" (`reasoning_content`) para os modelos que retornam isso.
- **Suporte a imagem** nos agentes que aceitam visão (Step-3.7 e MiniMax).
- **Gerenciar agentes pela própria interface** (só admin): adicionar, editar ou
  remover agentes — inclusive de outros provedores — sem mexer em código nem
  reiniciar o servidor.

## Estrutura do projeto

```
ai-hub/
├── backend/            FastAPI + SQLite
│   ├── main.py         rotas da API e arquivos estáticos
│   ├── database.py     schema do banco e agentes padrão
│   ├── auth.py         senha e sessão (cookie)
│   ├── ai_engine.py    chamadas aos modelos (streaming e não-streaming)
│   ├── bridge.py       lógica da conversa entre agentes
│   ├── .env            suas chaves de API (NÃO compartilhe este arquivo)
│   └── requirements.txt
└── frontend/           HTML + CSS + JS puro (sem build, sem Node)
    ├── index.html
    ├── css/style.css
    └── js/ (api.js, auth.js, app.js)
```

## Como rodar

Requer **Python 3.10+**. Nenhuma instalação de Node/npm é necessária — o
frontend é servido diretamente pelo backend.

```bash
cd ai-hub/backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Abra **http://localhost:8000** no navegador. Crie sua conta na tela de login —
como for o primeiro usuário, você já entra como administrador.

## Suas chaves de API

O arquivo `backend/.env` já vem preenchido com as 4 chaves que estavam nos
scripts que você enviou:

```
NVIDIA_API_KEY_GLM=...
NVIDIA_API_KEY_STEP3=...
NVIDIA_API_KEY_MINIMAX=...
NVIDIA_API_KEY_MISTRAL=...
```

**Importante sobre segurança:** essas chaves agora estão em texto puro nesse
arquivo. Trate-o como uma senha — não faça commit dele em repositórios
públicos, não o compartilhe. Como essas chaves passaram por esta conversa,
se você tiver qualquer dúvida sobre exposição, o mais seguro é regenerá-las
no painel da NVIDIA e colar as novas aqui. Também notei que os 4 scripts
usavam chaves diferentes entre si — se algum agente dessa lista der erro de
autenticação ao usar, é sinal de que aquela chave específica não é mais
válida; gere uma nova e atualize a linha correspondente no `.env`.

Não testei as chamadas reais aos 4 modelos: o ambiente onde eu desenvolvi este
app só tem acesso de rede a repositórios de pacotes (pip/npm/GitHub), não ao
`integrate.api.nvidia.com`. Simulei um servidor local com o mesmo formato de
resposta da NVIDIA para validar todo o pipeline (streaming, raciocínio,
salvamento no banco, ponte entre agentes, permissões) e tudo funcionou — mas
vale testar as chamadas reais assim que você rodar o app localmente.

## Adicionando novos agentes

Clique em **"Gerenciar agentes"** na barra lateral (aparece só para admins) e
preencha o formulário — identificador, nome, modelo, chave de API, e se aceita
imagem. Funciona para qualquer provedor compatível com o formato da API da
OpenAI (`/v1/chat/completions` com `model`, `messages`, etc.), não só NVIDIA.
O agente fica disponível para todos os usuários imediatamente.

## Como funciona a Ponte

Cada modelo de IA só entende uma conversa de duas pontas (você e ele). Para
simular vários participantes, a cada vez que é a vez de um agente falar, o
backend monta o histórico inteiro rotulando quem disse o quê
(`[Nome do agente]: mensagem`) e explica isso a ele por um prompt de sistema.
As falas do próprio agente em rodadas anteriores viram mensagens dele
("assistant"); todo o resto vira mensagens do tipo "usuário" identificadas por
nome. Isso é o que aparece de forma visual como cabos conectando os avatares
dos agentes quando uma ponte está em andamento.

## Limitações conhecidas e possíveis próximos passos

- As chaves de agentes adicionados pela interface ficam salvas em texto puro
  no `app_data.db` (nunca são devolvidas pela API). Para um uso mais exposto
  publicamente, vale adicionar criptografia em repouso.
- Não há limite de tentativas de login nem política de senha além do
  comprimento mínimo — dá para reforçar se o app for exposto na internet.
- A Ponte roda as chamadas em sequência (não em paralelo) para manter a ordem
  do diálogo; com muitos agentes/rodadas ela pode demorar alguns segundos.
- Para expor isso fora da sua rede local, coloque um proxy reverso com HTTPS
  na frente (nginx/Caddy) e marque o cookie de sessão como `secure`.
