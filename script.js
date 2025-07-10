class RAGInterface {
    constructor() {
        this.initializeElements();
        this.bindEvents();
        this.loadHistory();
        this.currentQuery = '';
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
            const response = await fetch('/api/query', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query: query })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('RAG API call failed:', error);
            
            return this.getMockResponse(query);
        }
    }

    getMockResponse(query) {
        return {
            answer: `質問「${query}」に対する回答です。これはモックの回答で、実際のRAGシステムからの応答ではありません。\n\n実際のシステムでは、この部分に関連するドキュメントから抽出された情報に基づいた回答が表示されます。`,
            sources: [
                {
                    header: "サンプル見出し1",
                    content: "これは引用元のサンプルコンテンツです。実際のシステムでは、ここに関連するドキュメントの内容が表示されます。",
                    doc_id: "sample_doc_1.md",
                    section_id: 1,
                    level: 2,
                    score: 0.95
                },
                {
                    header: "サンプル見出し2",
                    content: "別の引用元のサンプルコンテンツです。複数の引用元がある場合は、このように複数表示されます。",
                    doc_id: "sample_doc_2.md",
                    section_id: 3,
                    level: 1,
                    score: 0.87
                },
                {
                    header: "サンプル見出し3",
                    content: "さらに別の引用元です。関連度スコアによって順序が決まります。",
                    doc_id: "sample_doc_1.md",
                    section_id: 7,
                    level: 3,
                    score: 0.82
                }
            ]
        };
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

class RAGServer {
    constructor() {
        this.ragSystem = null;
        this.initializeServer();
    }

    async initializeServer() {
        console.log('RAGサーバーを初期化しています...');
        
        try {
            this.ragSystem = new RAGSystemMock();
            console.log('RAGサーバーの初期化が完了しました');
        } catch (error) {
            console.error('RAGサーバーの初期化に失敗しました:', error);
        }
    }

    async handleQuery(query) {
        if (!this.ragSystem) {
            throw new Error('RAGシステムが初期化されていません');
        }

        return await this.ragSystem.query(query);
    }
}

class RAGSystemMock {
    constructor() {
        this.documents = this.loadSampleDocuments();
    }

    loadSampleDocuments() {
        return [
            {
                id: 'doc1',
                title: 'プログラミング基礎',
                sections: [
                    { header: 'プログラミングとは', content: 'プログラミングは、コンピューターに指示を与えるためのコードを書く作業です。', level: 1 },
                    { header: 'Python入門', content: 'Pythonは初心者にやさしいプログラミング言語です。シンプルな構文と豊富なライブラリが特徴です。', level: 2 },
                    { header: 'JavaScript基礎', content: 'JavaScriptはWebブラウザで動作するプログラミング言語です。動的なWebページを作成できます。', level: 2 }
                ]
            },
            {
                id: 'doc2',
                title: 'データ分析',
                sections: [
                    { header: 'データ分析の重要性', content: 'データ分析は現代ビジネスにおいて重要な役割を果たしています。', level: 1 },
                    { header: 'データの収集', content: 'データ分析の第一歩は、適切なデータの収集です。様々な手法があります。', level: 2 },
                    { header: 'データの可視化', content: 'データを視覚的に表現することで、パターンや傾向を発見できます。', level: 2 }
                ]
            }
        ];
    }

    async query(queryText) {
        const queryLower = queryText.toLowerCase();
        const matchedSections = [];
        
        this.documents.forEach(doc => {
            doc.sections.forEach((section, index) => {
                const score = this.calculateScore(queryLower, section);
                if (score > 0.1) {
                    matchedSections.push({
                        header: section.header,
                        content: section.content,
                        doc_id: doc.id,
                        section_id: index,
                        level: section.level,
                        score: score
                    });
                }
            });
        });

        matchedSections.sort((a, b) => b.score - a.score);
        
        const topSections = matchedSections.slice(0, 3);
        
        const answer = this.generateAnswer(queryText, topSections);
        
        return {
            answer: answer,
            sources: topSections
        };
    }

    calculateScore(query, section) {
        const sectionText = (section.header + ' ' + section.content).toLowerCase();
        const queryWords = query.split(/\s+/);
        
        let score = 0;
        queryWords.forEach(word => {
            if (sectionText.includes(word)) {
                score += 0.3;
            }
        });
        
        return Math.min(score, 1.0);
    }

    generateAnswer(query, sections) {
        if (sections.length === 0) {
            return '申し訳ございませんが、関連する情報が見つかりませんでした。';
        }

        let answer = `「${query}」に関する情報をお答えします。\n\n`;
        
        sections.forEach((section, index) => {
            if (index < 2) {
                answer += `${section.header}について：\n${section.content}\n\n`;
            }
        });
        
        return answer.trim();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const ragInterface = new RAGInterface();
    const ragServer = new RAGServer();

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { RAGInterface, RAGServer, RAGSystemMock };
    }
    
    window.ragInterface = ragInterface;
    window.ragServer = ragServer;
});