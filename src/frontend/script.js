class RAGInterface {
    constructor() {
        this.initializeElements();
        this.bindEvents();
        this.loadHistory();
        this.currentQuery = '';
        this.baseUrl = window.location.origin;
    }

    initializeElements() {
        this.queryInput = document.getElementById('queryInput');
        this.searchButton = document.getElementById('searchButton');
        this.loadingIndicator = document.getElementById('loadingIndicator');
        this.resultContainer = document.getElementById('resultContainer');
        this.answerContent = document.getElementById('answerContent');
        this.sourcesContent = document.getElementById('sourcesContent');
        this.errorContainer = document.getElementById('errorContainer');
        this.errorContent = document.getElementById('errorContent');
        this.historyContent = document.getElementById('historyContent');
    }

    bindEvents() {
        this.searchButton.addEventListener('click', () => this.handleSearch());
        this.queryInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.handleSearch();
            }
        });
    }

    async handleSearch() {
        const query = this.queryInput.value.trim();
        if (!query) {
            this.showError('質問を入力してください。');
            return;
        }

        this.currentQuery = query;
        this.showLoading();
        this.hideError();

        try {
            const result = await this.queryRAG(query);
            this.displayResults(result);
            this.addToHistory(query);
        } catch (error) {
            this.showError(`エラーが発生しました: ${error.message}`);
        } finally {
            this.hideLoading();
        }
    }

    async queryRAG(query) {
        try {
            const response = await fetch(`${this.baseUrl}/api/query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query: query })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }

            return data;
        } catch (error) {
            console.error('RAG API call failed:', error);
            throw error;
        }
    }

    displayResults(result) {
        this.displayAnswer(result.answer);
        this.displaySources(result.sources);
        this.showResults();
    }

    displayAnswer(answer) {
        this.answerContent.innerHTML = '';
        
        const paragraphs = answer.split('\n\n');
        paragraphs.forEach(paragraph => {
            if (paragraph.trim()) {
                const p = document.createElement('p');
                p.textContent = paragraph.trim();
                p.style.marginBottom = '1em';
                this.answerContent.appendChild(p);
            }
        });
    }

    displaySources(sources) {
        this.sourcesContent.innerHTML = '';
        
        if (!sources || sources.length === 0) {
            const noSources = document.createElement('p');
            noSources.textContent = '引用元が見つかりませんでした。';
            noSources.style.color = '#7f8c8d';
            noSources.style.fontStyle = 'italic';
            this.sourcesContent.appendChild(noSources);
            return;
        }

        sources.forEach((source, index) => {
            const sourceItem = document.createElement('div');
            sourceItem.className = 'source-item';
            
            const header = document.createElement('div');
            header.className = 'source-header';
            header.innerHTML = `📄 ${source.header || 'セクション ' + (index + 1)}`;
            
            const content = document.createElement('div');
            content.className = 'source-content';
            content.textContent = source.content;
            
            const meta = document.createElement('div');
            meta.className = 'source-meta';
            meta.innerHTML = `
                📂 ${source.doc_id || 'unknown'} | 
                🎯 関連度: ${((source.score || 0) * 100).toFixed(1)}% | 
                📊 レベル: H${source.level || 1}
            `;
            
            sourceItem.appendChild(header);
            sourceItem.appendChild(content);
            sourceItem.appendChild(meta);
            
            this.sourcesContent.appendChild(sourceItem);
        });
    }

    showLoading() {
        this.loadingIndicator.style.display = 'block';
        this.resultContainer.style.display = 'none';
        this.searchButton.disabled = true;
        this.searchButton.textContent = '検索中...';
    }

    hideLoading() {
        this.loadingIndicator.style.display = 'none';
        this.searchButton.disabled = false;
        this.searchButton.textContent = '検索';
    }

    showResults() {
        this.resultContainer.style.display = 'grid';
        this.resultContainer.classList.add('fade-in');
    }

    showError(message) {
        this.errorContent.textContent = message;
        this.errorContainer.style.display = 'block';
        this.resultContainer.style.display = 'none';
    }

    hideError() {
        this.errorContainer.style.display = 'none';
    }

    addToHistory(query) {
        let history = JSON.parse(localStorage.getItem('ragHistory') || '[]');
        
        const historyItem = {
            query: query,
            timestamp: new Date().toISOString(),
            displayTime: new Date().toLocaleString('ja-JP')
        };
        
        history.unshift(historyItem);
        
        if (history.length > 10) {
            history = history.slice(0, 10);
        }
        
        localStorage.setItem('ragHistory', JSON.stringify(history));
        this.renderHistory();
    }

    loadHistory() {
        this.renderHistory();
    }

    renderHistory() {
        const history = JSON.parse(localStorage.getItem('ragHistory') || '[]');
        
        if (history.length === 0) {
            this.historyContent.innerHTML = '<p class="empty-history">検索履歴はありません</p>';
            return;
        }

        this.historyContent.innerHTML = '';
        
        history.forEach(item => {
            const historyItem = document.createElement('div');
            historyItem.className = 'history-item';
            historyItem.addEventListener('click', () => {
                this.queryInput.value = item.query;
                this.queryInput.focus();
            });
            
            const queryDiv = document.createElement('div');
            queryDiv.className = 'history-query';
            queryDiv.textContent = item.query;
            
            const timestampDiv = document.createElement('div');
            timestampDiv.className = 'history-timestamp';
            timestampDiv.textContent = item.displayTime;
            
            historyItem.appendChild(queryDiv);
            historyItem.appendChild(timestampDiv);
            
            this.historyContent.appendChild(historyItem);
        });
    }

    clearHistory() {
        localStorage.removeItem('ragHistory');
        this.renderHistory();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const ragInterface = new RAGInterface();
    
    window.ragInterface = ragInterface;
});