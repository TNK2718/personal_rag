class RAGInterface {
    constructor() {
        this.initializeElements();
        this.bindEvents();
        this.loadHistory();
        this.currentQuery = '';
        this.baseUrl = window.location.origin;
        this.todos = [];
        this.currentTab = 'search';
        this.initializeTabs();
    }

    initializeElements() {
        // RAG要素
        this.queryInput = document.getElementById('queryInput');
        this.searchButton = document.getElementById('searchButton');
        this.loadingIndicator = document.getElementById('loadingIndicator');
        this.resultContainer = document.getElementById('resultContainer');
        this.answerContent = document.getElementById('answerContent');
        this.sourcesContent = document.getElementById('sourcesContent');
        this.errorContainer = document.getElementById('errorContainer');
        this.errorContent = document.getElementById('errorContent');
        this.historyContent = document.getElementById('historyContent');
        
        // タブ要素
        this.navTabs = document.querySelectorAll('.nav-tab');
        this.searchTab = document.getElementById('searchTab');
        this.todosTab = document.getElementById('todosTab');
        
        // TODO要素
        this.extractTodosBtn = document.getElementById('extractTodosBtn');
        this.statusFilter = document.getElementById('statusFilter');
        this.todoInput = document.getElementById('todoInput');
        this.prioritySelect = document.getElementById('prioritySelect');
        this.addTodoBtn = document.getElementById('addTodoBtn');
        this.todoLoadingIndicator = document.getElementById('todoLoadingIndicator');
        this.todoList = document.getElementById('todoList');
    }

    bindEvents() {
        // RAGイベント
        this.searchButton.addEventListener('click', () => this.handleSearch());
        this.queryInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.handleSearch();
            }
        });
        
        // TODOイベント
        this.extractTodosBtn.addEventListener('click', () => this.extractTodos());
        this.statusFilter.addEventListener('change', () => this.filterTodos());
        this.addTodoBtn.addEventListener('click', () => this.addTodo());
        this.todoInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.addTodo();
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
    
    // タブ機能
    initializeTabs() {
        this.navTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const tabName = tab.dataset.tab;
                this.switchTab(tabName);
            });
        });
        
        // 初期表示でTODOを読み込み
        this.loadTodos();
    }
    
    switchTab(tabName) {
        this.currentTab = tabName;
        
        // タブボタンのアクティブ状態を更新
        this.navTabs.forEach(tab => {
            tab.classList.remove('active');
            if (tab.dataset.tab === tabName) {
                tab.classList.add('active');
            }
        });
        
        // タブコンテンツを更新
        this.searchTab.classList.remove('active');
        this.todosTab.classList.remove('active');
        
        if (tabName === 'search') {
            this.searchTab.classList.add('active');
        } else if (tabName === 'todos') {
            this.todosTab.classList.add('active');
        }
    }
    
    // TODO機能
    async loadTodos() {
        try {
            const response = await fetch(`${this.baseUrl}/api/todos`);
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            this.todos = data.todos;
            this.renderTodos();
        } catch (error) {
            console.error('TODO読み込みエラー:', error);
        }
    }
    
    async extractTodos() {
        this.showTodoLoading();
        
        try {
            const response = await fetch(`${this.baseUrl}/api/todos/extract`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            alert(data.message);
            await this.loadTodos();
        } catch (error) {
            alert(`TODO抽出エラー: ${error.message}`);
        } finally {
            this.hideTodoLoading();
        }
    }
    
    async addTodo() {
        const content = this.todoInput.value.trim();
        if (!content) {
            alert('TODOを入力してください。');
            return;
        }
        
        const priority = this.prioritySelect.value;
        
        try {
            const response = await fetch(`${this.baseUrl}/api/todos`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    content: content,
                    priority: priority
                })
            });
            
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            this.todoInput.value = '';
            await this.loadTodos();
        } catch (error) {
            alert(`TODO追加エラー: ${error.message}`);
        }
    }
    
    async updateTodo(todoId, updates) {
        try {
            const response = await fetch(`${this.baseUrl}/api/todos/${todoId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(updates)
            });
            
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            await this.loadTodos();
        } catch (error) {
            alert(`TODO更新エラー: ${error.message}`);
        }
    }
    
    async deleteTodo(todoId) {
        if (!confirm('TODOを削除しますか？')) {
            return;
        }
        
        try {
            const response = await fetch(`${this.baseUrl}/api/todos/${todoId}`, {
                method: 'DELETE'
            });
            
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            
            await this.loadTodos();
        } catch (error) {
            alert(`TODO削除エラー: ${error.message}`);
        }
    }
    
    filterTodos() {
        this.renderTodos();
    }
    
    renderTodos() {
        const statusFilter = this.statusFilter.value;
        const filteredTodos = statusFilter ? 
            this.todos.filter(todo => todo.status === statusFilter) : 
            this.todos;
        
        if (filteredTodos.length === 0) {
            this.todoList.innerHTML = '<div class="empty-todos">メモからTODOを抽出するか、手動で追加してください。</div>';
            return;
        }
        
        this.todoList.innerHTML = '';
        
        filteredTodos.forEach(todo => {
            const todoItem = document.createElement('div');
            todoItem.className = `todo-item priority-${todo.priority} status-${todo.status}`;
            
            todoItem.innerHTML = `
                <input type="checkbox" class="todo-checkbox" ${todo.status === 'completed' ? 'checked' : ''} 
                       onchange="ragInterface.toggleTodoStatus('${todo.id}')">
                <div class="todo-content">
                    <div class="todo-text ${todo.status === 'completed' ? 'completed' : ''}">${todo.content}</div>
                    <div class="todo-meta">
                        <span class="status-badge ${todo.status}">${this.getStatusText(todo.status)}</span>
                        <span class="priority-badge ${todo.priority}">${this.getPriorityText(todo.priority)}</span>
                        <span>ソース: ${todo.source_file} > ${todo.source_section}</span>
                        <span>作成: ${new Date(todo.created_at).toLocaleString('ja-JP')}</span>
                    </div>
                </div>
                <div class="todo-actions">
                    <button class="todo-action-btn edit-btn" onclick="ragInterface.editTodo('${todo.id}')">Edit</button>
                    <button class="todo-action-btn delete-btn" onclick="ragInterface.deleteTodo('${todo.id}')">Delete</button>
                </div>
            `;
            
            this.todoList.appendChild(todoItem);
        });
    }
    
    async toggleTodoStatus(todoId) {
        const todo = this.todos.find(t => t.id === todoId);
        if (!todo) return;
        
        const newStatus = todo.status === 'completed' ? 'pending' : 'completed';
        await this.updateTodo(todoId, { status: newStatus });
    }
    
    editTodo(todoId) {
        const todo = this.todos.find(t => t.id === todoId);
        if (!todo) return;
        
        const newContent = prompt('TODOを編集:', todo.content);
        if (newContent && newContent.trim() !== todo.content) {
            this.updateTodo(todoId, { content: newContent.trim() });
        }
    }
    
    getStatusText(status) {
        const statusMap = {
            'pending': '未完了',
            'in_progress': '進行中',
            'completed': '完了'
        };
        return statusMap[status] || status;
    }
    
    getPriorityText(priority) {
        const priorityMap = {
            'high': '高',
            'medium': '中',
            'low': '低'
        };
        return priorityMap[priority] || priority;
    }
    
    showTodoLoading() {
        this.todoLoadingIndicator.style.display = 'block';
        this.extractTodosBtn.disabled = true;
        this.addTodoBtn.disabled = true;
    }
    
    hideTodoLoading() {
        this.todoLoadingIndicator.style.display = 'none';
        this.extractTodosBtn.disabled = false;
        this.addTodoBtn.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const ragInterface = new RAGInterface();
    
    window.ragInterface = ragInterface;
});