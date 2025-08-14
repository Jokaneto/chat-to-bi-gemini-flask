# JOKA.AI: Um BI Conversacional com Gemini, Flask e Google Drive

Este projeto é uma aplicação web de Business Intelligence (BI) que permite aos usuários fazer perguntas em linguagem natural sobre seus dados e receber respostas textuais e gráficos interativos gerados por IA.

![GIF do App em Ação](link_para_um_gif_do_seu_app.gif)  <-- *Isso é muito importante! Grave um GIF!*

## Como Funciona?

A aplicação utiliza uma arquitetura híbrida inteligente:

1.  **Frontend (HTML/JS):** O usuário digita uma pergunta (ex: "Qual o total de vendas por parceiro este ano?").
2.  **Backend (Flask):** O servidor recebe a pergunta.
3.  **Fonte de Dados (Google Drive):** Os dados brutos (arquivos CSV) são lidos de uma pasta no Google Drive e mantidos em cache. Uma rotina em segundo plano verifica por atualizações nos arquivos a cada minuto.
4.  **Cérebro de IA (Google Gemini):** O backend envia a pergunta do usuário, o esquema dos dados e o histórico da conversa para a API do Gemini.
5.  **Plano de Ação:** Gemini não calcula a resposta final. Em vez disso, ele retorna um "plano de ação" em formato JSON, especificando como os dados devem ser filtrados, agrupados e que tipo de gráfico deve ser criado.
6.  **Executor (Pandas & Plotly):** O backend executa esse plano usando Pandas para manipular os dados e Plotly para gerar os gráficos interativos.
7.  **Resposta Final:** A resposta em texto e os gráficos são enviados de volta para o usuário no navegador.

## Features

-   **Análise em Linguagem Natural:** Converse com seus dados.
-   **Live-Reload:** Atualize os arquivos CSV no Google Drive e a aplicação refletirá as mudanças automaticamente.
-   **Geração Dinâmica de Gráficos:** Crie gráficos de barras, pizza e mais, apenas pedindo.
-   **Memória Conversacional:** Faça perguntas de acompanhamento e a IA entenderá o contexto.
-   **Open-Source:** Adapte, melhore e use como base para seus próprios projetos!

## Como Executar Localmente

1.  **Clone o Repositório**
    ```bash
    git clone [https://github.com/seu-usuario/seu-repositorio.git](https://github.com/seu-usuario/seu-repositorio.git)
    cd seu-repositorio
    ```

2.  **Instale as Dependências**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure as Credenciais**
    * Siga o guia do Google para criar uma **Conta de Serviço** e obter o arquivo `credentials.json`. [Link para o Guia do Google aqui]
    * Ative a API do Google Drive e a API do Gemini no seu projeto Google Cloud.
    * Renomeie `credentials.json.template` para `credentials.json` e preencha com suas chaves.

4.  **Configure as Variáveis de Ambiente**
    * Você precisa definir sua chave da API do Gemini. No Linux/macOS:
        ```bash
        export GEMINI_API_KEY="sua_chave_aqui"
        ```
    * No código (`app.py`), altere a variável `GOOGLE_DRIVE_FOLDER_ID` para o ID da sua pasta no Drive e a `SECRET_KEY` do Flask.

5.  **Rode a Aplicação**
    ```bash
    python app.py
    ```
    Acesse `http://127.0.0.1:5000` no seu navegador.

## Como Contribuir

Contribuições são muito bem-vindas! Se você tem ideias para melhorias, novos recursos ou encontrou um bug:

1.  Faça um Fork do projeto.
2.  Crie uma nova Branch (`git checkout -b feature/sua-feature`).
3.  Faça suas alterações.
4.  Envie um Pull Request.

---