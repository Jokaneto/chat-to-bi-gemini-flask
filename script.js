/**
 * Este script controla a interface do chat, enviando as perguntas do usuário
 * para o backend Flask e renderizando a resposta, que pode conter texto,
 * insights e múltiplos gráficos interativos do Plotly.
 */
document.addEventListener('DOMContentLoaded', () => {
    // Atalhos para os elementos HTML com os quais vamos interagir
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const messagesContainer = document.getElementById('messages');
    const initialPlaceholder = "Faça uma pergunta sobre seus dados...";

    userInput.placeholder = initialPlaceholder;

    /**
     * Adiciona uma mensagem de texto (do usuário ou do bot) ao chat.
     * @param {string} markdownText - O conteúdo da mensagem em formato Markdown.
     * @param {string} sender - 'user' ou 'bot'.
     */
    function addTextMessage(markdownText, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', `${sender}-message`);
        // A biblioteca 'marked.js' (importada no index.html) converte Markdown para HTML
        messageDiv.innerHTML = marked.parse(markdownText);
        messagesContainer.appendChild(messageDiv);
        scrollToBottom();
    }
    
    /**
     * Adiciona o bloco de "Insight" ao chat, se ele existir na resposta.
     * @param {string} markdownText - O texto do insight em formato Markdown.
     */
    function addInsightMessage(markdownText) {
        if (!markdownText) return; // Não faz nada se o texto for nulo
        const insightDiv = document.createElement('div');
        insightDiv.classList.add('message', 'insight-message');
        insightDiv.innerHTML = `💡 <strong>Insight:</strong><p>${marked.parse(markdownText)}</p>`;
        messagesContainer.appendChild(insightDiv);
    }

    /**
     * Cria um container e renderiza um gráfico Plotly dentro dele.
     * @param {object} chartSpec - A especificação do gráfico em JSON (data e layout).
     * @param {HTMLElement} parentElement - O elemento pai onde o gráfico será adicionado.
     */
    function addChart(chartSpec, parentElement) {
        // Cria um novo <div> para ser o container do gráfico
        const chartContainer = document.createElement('div');
        // Cria um ID que é garantido ser único usando a data/hora e um número aleatório
        const chartId = `chart-${Date.now()}-${Math.random()}`; // Gera um ID único para o gráfico
        chartContainer.id = chartId; // Define o ID do container
        chartContainer.classList.add('chart-container'); // Adiciona uma classe para estilização
        
        // Adiciona o container de gráfico ao seu pai especificado
        parentElement.appendChild(chartContainer);
        
        // Usa setTimeout para garantir que o div foi adicionado ao DOM antes de o Plotly tentar desenhar.
        // Isso previne erros de renderização em alguns navegadores.
        setTimeout(() => {
            try {
                Plotly.newPlot(chartContainer, chartSpec.data, chartSpec.layout, { responsive: true, useResizeHandler: true });
            } catch(e) {
                console.error("Erro ao desenhar o gráfico com Plotly:", e, chartSpec);
                chartContainer.innerHTML = "<p style='color: red;'>Ocorreu um erro ao tentar desenhar este gráfico.</p>";
            }
        }, 100); // 100ms de atraso é seguro e imperceptível.
    }
    
    /** Envia a visão do chat para a mensagem mais recente. */
    function scrollToBottom() {
        const wrapper = document.querySelector('.main-content-wrapper');
        if (wrapper) {
            setTimeout(() => { wrapper.scrollTop = wrapper.scrollHeight; }, 100);
        }
    }

    /** Função principal: envia a pergunta para o backend e processa a resposta. */
    async function sendMessage() {
        const question = userInput.value.trim();
        if (!question) return;

        // 1. Prepara a UI para a requisição
        addTextMessage(question, 'user');
        userInput.value = '';
        const typingMessage = document.createElement('div');
        typingMessage.id = 'typing-indicator';
        typingMessage.classList.add('message', 'bot-message');
        typingMessage.innerHTML = '<span>Analisando...</span>';
        messagesContainer.appendChild(typingMessage);
        scrollToBottom();
        userInput.disabled = true;
        sendButton.disabled = true;

        try {
            // 2. Envia a pergunta para o backend
            const response = await fetch('/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: question })
            });
            document.getElementById('typing-indicator')?.remove(); // Remove o "Analisando..."
            if (!response.ok) throw new Error(`Erro HTTP! Status: ${response.status}`);
            
            // 3. Processa a resposta JSON recebida
            const data = await response.json();
            if (data.answer) addTextMessage(data.answer, 'bot');
            if (data.insight_text) addInsightMessage(data.insight_text);

            // 4. Lógica para renderizar um ou múltiplos gráficos
            if (data.charts_json && data.charts_json.length > 0) {
                if (data.charts_json.length > 1) {
                    // Se houver mais de um gráfico, cria o container para o layout lado a lado
                    const multiChartWrapper = document.createElement('div');
                    multiChartWrapper.classList.add('multi-chart-wrapper');
                    messagesContainer.appendChild(multiChartWrapper);
                    // Desenha cada gráfico dentro deste wrapper
                    data.charts_json.forEach((chartSpec) => { addChart(chartSpec, multiChartWrapper); });
                } else {
                    // Se for apenas um gráfico, desenha diretamente na área de mensagens
                    addChart(data.charts_json[0], messagesContainer);
                }
            }
        } catch (error) {
            console.error('Erro ao enviar a pergunta:', error);
            document.getElementById('typing-indicator')?.remove();
            addTextMessage('Desculpe, houve um erro. Por favor, verifique o console do servidor.', 'bot');
        } finally {
            // 5. Reativa a UI
            userInput.disabled = false;
            sendButton.disabled = false;
            userInput.focus();
        }
    }

    // Eventos que disparam a função sendMessage
    sendButton.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault(); // Evita que o Enter pule uma linha no input
            sendMessage();
        }
    });
});