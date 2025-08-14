# --- 1. IMPORTS DE BIBLIOTECAS ---

import os
import io
import json
import time
import threading
import traceback
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import google.generativeai as genai
from flask import Flask, request, jsonify, session, send_from_directory
from flask_caching import Cache
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

# --- 2. CONFIGURAÇÃO INICIAL DA APLICAÇÃO ---

# Inicializa a aplicação Flask
app = Flask(__name__)

# Define uma chave secreta, essencial para a funcionalidade de 'session' (histórico da conversa)
# É importante que esta chave seja um valor complexo e secreto em um ambiente de produção.
app.config['SECRET_KEY'] = 'substitua-pela-sua-chave-secreta-aleatoria-e-forte'

# Configura o sistema de cache. Usamos um cache simples em memória que expira a cada 1 hora (3600 segundos).
# Isso significa que os dados do Google Drive só serão recarregados do zero uma vez por hora,
# ou quando um arquivo for modificado.
cache = Cache(app, config={
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 3600
})

# --- 3. CONFIGURAÇÃO DAS APIS E CONSTANTES GLOBAIS ---

# Carrega a chave da API do Gemini a partir das variáveis de ambiente do sistema.
# Esta é a forma mais segura de gerenciar chaves, evitando colocá-las diretamente no código.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("ERRO CRÍTICO: A variável de ambiente GEMINI_API_KEY não está configurada.")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("models/gemini-1.5-flash")

# Constantes para a API do Google Drive
SCOPES = ['https://www.googleapis.com/auth/drive.readonly'] # Define que nossa aplicação terá apenas permissão de leitura.
CREDENTIALS_FILE = 'credentials.json' # O nome do arquivo com as credenciais da conta de serviço.
GOOGLE_DRIVE_FOLDER_ID = '1bwIEltfclW0XgRKfLxlIbyKLnJE0No8W' # O ID da sua pasta no Google Drive.
drive_service = None  # A variável que guardará a conexão com a API do Drive. Será inicializada mais tarde.

# Variáveis globais para comunicação entre a thread de atualização e a carga de dados
csv_modification_times = {} # Dicionário para rastrear a "versão" (data de modificação) de cada arquivo CSV.
INTERVALO_DE_VERIFICACAO = 60 # Define o intervalo em segundos para a rotina de verificação (aqui, 1 minuto).

# --- 4. TEMPLATE DO PROMPT PARA O GEMINI ---

# Este é o modelo de texto que será preenchido com os dados da pergunta e enviado ao Gemini.
# A estrutura é crucial para garantir que a resposta do Gemini seja consistente e no formato JSON que esperamos.
PROMPT_TEMPLATE = """
    Você é um assistente de análise de dados. Com base no histórico da conversa, esquema, dados e na nova pergunta, forneça:
    1. `answer`: Uma resposta em texto.
    2. `insight_text`: Uma observação ou insight interessante sobre a análise. Se não houver, deixe nulo.
    3. `chart_plans`: UMA LISTA de planos de gráfico em JSON. Se nenhum gráfico for necessário, a lista deve ser vazia `[]`.

    REGRAS IMPORTANTES:
    - Se o usuário pedir para agrupar por mês, use `group_by: ["Ano-Mês"]`.
    - Para gráficos de barras agrupadas, use o campo `color` no plano para indicar a coluna de agrupamento secundária.
    - VOCÊ DEVE SEMPRE USAR O OBJETO `data_transformation` para descrever como os dados devem ser processados.

    O JSON 'chart_plan' deve ter a estrutura: `chart_type`, `title`, `color` (opcional), `data_transformation` (`filters`, `group_by`, `aggregation`), `x_axis`, `y_axis`.
    ---
    Histórico da Conversa:
    {conversation_history}
    ---
    Esquema do DataFrame (Tipos de Dados):
    {schema_info}
    ---
    Exemplo de Dados (5 primeiras linhas):
    {data_summary}
    ---
    Pergunta do Usuário:
    "{question}"
    ---
    Sua Resposta (em formato JSON VÁLIDO):
    ```json
    {{
    "answer": "Sua resposta em texto aqui.",
    "insight_text": null,
    "chart_plans": []
    }}
"""
### Detalhando o Prompt:
# Definição do Papel:** Começamos dizendo ao Gemini qual é o seu papel ("Você é um assistente de análise de dados").
# Estrutura da Resposta:** Damos uma ordem clara sobre os 3 campos que queremos na resposta: `answer`, `insight_text`, e `chart_plans`.
# Regras Importantes:** Ensinamos a ele regras específicas do nosso sistema, como usar `"Ano-Mês"` para agrupamentos mensais. A regra em caixa alta é para dar ênfase extra.
# Placeholders (`{...}`):** Os campos como `{conversation_history}`, `{schema_info}`, etc., são os espaços que nosso código Python preencherá com os dados relevantes a cada nova pergunta.
# Exemplo de Saída:** O bloco `json {{...}}` no final serve como um exemplo claro para o Gemini de como ele deve formatar sua resposta, garantindo que receberemos um JSON válido. As chaves duplas `{{` e `}}` são para que o Python não tente formatar essa parte.

# --- 5. FUNÇÕES AUXILIARES E DE LÓGICA ---

def authenticate_google_drive():
    """Autentica com a API do Google Drive usando as credenciais de conta de serviço."""
    try:
        info = json.load(open(CREDENTIALS_FILE))
        creds = ServiceAccountCredentials.from_service_account_info(info, scopes=SCOPES)
        print("Credenciais do Google Drive carregadas com sucesso.")
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Erro fatal na autenticação do Google Drive: {e}")
        return None

def extrair_json(text):
    """Função de segurança que extrai um bloco JSON de uma string de texto."""
    try:
        # Encontra o primeiro '{' e o último '}' para capturar o objeto JSON
        start_index = text.find('{')
        end_index = text.rfind('}') + 1
        if start_index == -1 or end_index == 0: return None
        # Converte a string encontrada em um objeto Python (dicionário)
        return json.loads(text[start_index:end_index])
    except Exception as e:
        print(f"Erro ao extrair JSON: {e}")
        return None

@cache.memoize()
def get_data():
    """
    Busca os dados do Google Drive, processa-os, une-os e retorna o DataFrame final.
    O decorador @cache.memoize() armazena o resultado. Se a função for chamada novamente,
    o resultado em cache é retornado instantaneamente, em vez de baixar tudo de novo.
    """
    global csv_modification_times # Acessa a variável global para atualizar os tempos dos arquivos
    print("INICIANDO CARGA COMPLETA DO GOOGLE DRIVE (NÃO DO CACHE)...")
    if not drive_service: return None
    
    local_dataframes = {}
    csv_files = {
        'parceiros.csv': 'parceiros', 'clientes.csv': 'clientes', 'contas.csv': 'contas',
        'movimentos_contas.csv': 'movimentos', 'classificacao_ultimo_movimento.csv': 'classificacao'
    }
    
    try:
        results = drive_service.files().list(
            q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and mimeType='text/csv'",
            fields="files(id, name, modifiedTime)").execute()
        items = results.get('files', [])

        for item in items:
            df_name = csv_files.get(item['name'].lower())
            if not df_name: continue
            
            request_file = drive_service.files().get_media(fileId=item['id'])
            df = pd.read_csv(io.BytesIO(request_file.execute()))
            csv_modification_times[item['name']] = item['modifiedTime']
            local_dataframes[df_name] = df
        
        # Processamento e Merge dos DataFrames
        df_mov = local_dataframes['movimentos']
        df_class = local_dataframes['classificacao']
        df_class.rename(columns={'Data_Ultimo_Movimento': 'Data_Movimento'}, inplace=True)
        
        final_df = df_mov.merge(local_dataframes['contas'], on="ID_Conta", how="left") \
                         .merge(local_dataframes['clientes'], on="ID_Cliente", how="left") \
                         .merge(df_class, on="ID_Conta", how="left", suffixes=('_mov', '_class')) \
                         .merge(local_dataframes['parceiros'], on="ID_Parceiro", how="left")
        
        # Converte todas as colunas que contêm 'Data' em seu nome para o tipo datetime do Pandas
        for col in final_df.columns:
            if 'Data' in col:
                final_df[col] = pd.to_datetime(final_df[col], errors='coerce')

        print(">>> DADOS CARREGADOS E PROCESSADOS COM SUCESSO. <<<")
        return final_df

    except Exception as e:
        print(f"ERRO CRÍTICO durante a carga de dados: {e}"); traceback.print_exc()
        return None

# <<< VERSÃO FINAL E FLEXÍVEL >>>
def gerar_grafico_plotly(plan, df_original):
    """
    Gera a especificação JSON de um gráfico Plotly a partir de um plano.
    Esta versão é flexível para lidar com pequenas variações na resposta da IA.
    """
    try:
        print(f"--- Iniciando Geração de Gráfico (Modo Manual Robusto) ---"); print(f"Plano recebido: {plan}")
        df = df_original.copy()
        transformation = plan.get('data_transformation')
        if not transformation: return None

        # 1. Filtros
        filters = transformation.get('filters', [])
        for f in filters:
            # <<< CORREÇÃO AQUI: O código agora entende 'operator' E 'condition' >>>
            column = f['column']
            operator = f.get('operator') or f.get('condition') # Pega o que existir
            value = f.get('value') or f.get('values')

            if not operator: # Pula o filtro se não houver operador
                print(f"AVISO: Filtro para coluna '{column}' sem operador. Pulando.")
                continue

            if "Data" in column and not pd.api.types.is_datetime64_any_dtype(df[column]):
                df[column] = pd.to_datetime(df[column], errors='coerce')
            
            print(f"Aplicando filtro: {column} {operator} {value}")
            if operator == 'between' and isinstance(value, list) and len(value) == 2:
                start_date, end_date = pd.to_datetime(value[0]), pd.to_datetime(value[1])
                df = df[df[column].between(start_date, end_date)]
            elif operator == 'in' and isinstance(value, list):
                df = df[df[column].isin(value)]
            else:
                df = df.query(f"`{column}` {operator} @value", local_dict={'value': value})
        
        if df.empty: return None

        # 2. Agrupamento
        group_by_cols = transformation.get('group_by', [])
        agg_info = transformation.get('aggregation', {})
        # <<< CORREÇÃO: Lida com agregação em formato de dicionário >>>
        if isinstance(agg_info, dict) and len(agg_info) == 1:
             agg_col = next(iter(agg_info))
             agg_func = agg_info[agg_col]
        else:
             agg_col, agg_func = agg_info.get('column'), agg_info.get('function')
        
        color_col = plan.get('color')
        if color_col and color_col not in group_by_cols: group_by_cols.append(color_col)
        
        if 'Ano-Mês' in group_by_cols:
            df['Ano-Mês'] = df['Data_Movimento_mov'].dt.to_period('M').astype(str)
        
        if group_by_cols and agg_col and agg_func:
            df_agg = df.groupby(list(set(group_by_cols))).agg({agg_col: agg_func}).reset_index()
        else:
            df_agg = df
            
        if df_agg.empty: return None
        
        chart_type, title, x_axis, y_axis = plan.get('chart_type'), plan.get('title'), plan.get('x_axis'), agg_col
        color_col = plan.get('color')
        fig = None

        print("Construindo gráfico com Plotly Express (px)...")

        if chart_type == 'bar':
            # Garante que o eixo X seja 'Ano-Mês' se o agrupamento foi feito assim
            if 'Ano-Mês' in df_agg.columns:
                x_axis = 'Ano-Mês'
            
            # Ordena os dados para garantir que os meses apareçam em ordem no gráfico
            df_agg = df_agg.sort_values(by=x_axis)

            # Usamos a função de alto nível para criar o gráfico.
            # Note que não passamos mais o parâmetro 'text' aqui.
            fig = px.bar(
                df_agg, 
                x=x_axis, 
                y=y_axis, 
                color=color_col,
                title=title
            )
            
            # <<< A CORREÇÃO FINAL E DEFINITIVA PARA OS RÓTULOS >>>
            # Dizemos ao gráfico para usar os valores do eixo Y ('y') como texto,
            # e aplicamos a formatação de número inteiro com separador de milhar (ex: 1,500).
            fig.update_traces(
                texttemplate='%{value:,.0f}', 
                textposition='outside'
            )
            
            # Garante que as colunas fiquem lado a lado
            fig.update_layout(barmode='group')

        elif chart_type in ['pie', 'donut']:
            fig = px.pie(df_agg, names=x_axis, values=y_axis, hole=0.4 if chart_type == 'donut' else 0, title=title)
            fig.update_traces(textinfo='percent+label', texttemplate='%{label}<br>%{percent:1.1%}')

        if fig:
            # Unifica os comandos de layout em um só para clareza
            fig.update_layout(
                title_text=title,
                title_x=0.5,
                legend_title_text='',
                margin=dict(t=60, b=80, l=10, r=40), 
                paper_bgcolor='rgba(0,0,0,0)', # Fundo externo transparente
                plot_bgcolor='rgba(0,0,0,0)', # Fundo da área do gráfico transparente
                title_font=dict(size=15), # Tamanho da fonte do título
                legend=dict(
                    orientation= "h", # Coloca a legenda na horizontal
                    yanchor="top",   # O ponto de ancoragem é o topo da legenda
                    y=1.1,          # Coloca a âncora em 98% da altura (bem no topo)
                    xanchor="left",  # O ponto de ancoragem é a esquerda da legenda
                    x=0.01           # Coloca a âncora em 1% da largura (bem na esquerda)
                )
            )
            return json.loads(fig.to_json())
        return None
    except Exception as e:
        print(f"ERRO FATAL ao gerar gráfico dinâmico: {e}"); traceback.print_exc()
        return None
        
# --- 6. ROTINA DE ATUALIZAÇÃO EM SEGUNDO PLANO ---
def verificar_atualizacoes_periodicamente():
    """
    Esta função roda em uma thread separada em um loop infinito,
    verificando o Google Drive por mudanças em intervalos regulares.
    """
    global csv_modification_times # Acessa o dicionário global para comparar as datas de modificação

    while True:
        # Pausa a execução pelo tempo definido na constante INTERVALO_DE_VERIFICACAO
        time.sleep(INTERVALO_DE_VERIFICACAO)
        print("\nVerificando atualizações no Google Drive...")

        # Se a conexão com o Drive não foi estabelecida, pula esta verificação
        if not drive_service:
            continue
        
        try:
            # Pede à API do Drive a lista de arquivos CSV e suas datas de modificação
            results = drive_service.files().list(
                q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and mimeType='text/csv'",
                fields="files(id, name, modifiedTime)").execute()
            items = results.get('files', [])

            for item in items:
                # Compara a data de modificação do arquivo no Drive com a data que temos guardada
                if item['name'] in csv_modification_times and csv_modification_times[item['name']] != item['modifiedTime']:
                    print(f"Mudança detectada em '{item['name']}'. Limpando o cache.")
                    
                    # Se houver mudança, limpa todo o cache da aplicação.
                    # A próxima vez que um usuário fizer uma pergunta, a função get_data()
                    # será forçada a baixar os dados novos do Drive.
                    cache.clear()
                    
                    # Chama get_data() para recarregar os dados imediatamente e atualizar
                    # os tempos de modificação, evitando limpezas repetidas.
                    get_data() 
                    
                    # Sai do loop 'for' pois o cache já foi limpo.
                    break 
        except Exception as e:
            print(f"Erro na rotina de verificação periódica: {e}")

# --- 7. ROTAS DA APLICAÇÃO WEB (FLASK) ---

@app.route('/')
def home():
    """Serve a página principal da aplicação (o arquivo index.html)."""
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static_files(path):
    """
    Serve arquivos estáticos como CSS, JS, imagens e fontes.
    Qualquer arquivo que o index.html pedir, esta rota vai encontrar e entregar.
    """
    return send_from_directory('.', path)

@app.route("/ask", methods=["POST"])
def ask_gemini():
    """
    Esta é a rota principal da API. Ela é chamada pelo JavaScript toda vez
    que o usuário envia uma nova pergunta.
    """
    # 1. Obter os dados (do cache, se disponível, ou do Drive se o cache estiver vazio)
    df = get_data()
    if df is None:
        return jsonify({"answer": "Desculpe, os dados não estão disponíveis no momento para análise."}), 500
    
    # 2. Gerenciar o histórico da conversa usando a 'session' do Flask
    if 'history' not in session:
        session['history'] = []
    
    # 3. Extrair a pergunta do corpo da requisição JSON enviada pelo JavaScript
    data = request.get_json()
    question = data.get("question")
    if not question:
        return jsonify({"answer": "Por favor, faça uma pergunta."}), 400

    # 4. Preparar todas as partes do prompt para o Gemini
    conversation_history = "\n".join([f"Usuário: {h['q']}\nAssistente: {h['a']}" for h in session['history']])
    prompt = PROMPT_TEMPLATE.format(
        conversation_history=conversation_history,
        schema_info=df.dtypes.to_string(), # Envia os tipos de dados das colunas
        data_summary=df.head(5).to_string(), # Envia as 5 primeiras linhas como exemplo
        question=question
    )
    
    try:
        # 5. Chamar a API do Gemini e processar a resposta
        response = model.generate_content(prompt)
        response_json = extrair_json(response.text)
        if not response_json:
            return jsonify({"answer": "Não consegui processar a resposta do modelo. Tente novamente."}), 500

        # Extrai cada parte da resposta JSON
        text_answer = response_json.get("answer")
        insight_text = response_json.get("insight_text")
        chart_plans = response_json.get("chart_plans", [])
        
        # 6. Gera os gráficos com base nos planos recebidos
        # Usa uma "list comprehension" para criar a lista de especificações de gráficos
        charts_json = [spec for plan in chart_plans if (spec := gerar_grafico_plotly(plan, df)) is not None]
        
        # 7. Atualiza o histórico da conversa com a pergunta atual e a resposta
        session['history'].append({'q': question, 'a': text_answer})
        # Mantém o histórico com no máximo os 3 últimos turnos da conversa
        if len(session['history']) > 3:
            session['history'].pop(0)
        session.modified = True
        
        # 8. Retorna a resposta completa para o JavaScript no formato JSON
        return jsonify({
            "answer": text_answer,
            "insight_text": insight_text,
            "charts_json": charts_json
        })
    except Exception as e:
        print(f"Erro geral na rota /ask: {e}"); traceback.print_exc()
        return jsonify({"answer": "Ocorreu um erro inesperado ao processar sua pergunta."}), 500

# --- 8. INICIALIZAÇÃO DA APLICAÇÃO ---
if __name__ == '__main__':
    # Primeiro, tenta autenticar com o Google Drive
    drive_service = authenticate_google_drive()
    
    # Se a autenticação for bem-sucedida, continua com a inicialização
    if drive_service:
        # Chama a função get_data() uma vez para fazer a carga inicial 
        # e popular o cache. A primeira pergunta do usuário será mais rápida.
        print("Realizando carga inicial dos dados para o cache...")
        get_data() 
        
        # Cria e inicia a thread que vai verificar por atualizações nos arquivos
        # em segundo plano, sem travar a aplicação principal.
        print("Iniciando a rotina de verificação de atualizações em segundo plano...")
        update_thread = threading.Thread(target=verificar_atualizacoes_periodicamente, daemon=True)
        update_thread.start()
    
    # Inicia o servidor Flask. 
    # use_reloader=False é essencial para que a thread de atualização não seja duplicada.
    print("Servidor Flask iniciado. Acesse http://127.0.0.1:5000 no seu navegador.")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)


