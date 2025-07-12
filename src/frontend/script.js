class RAGInterface {
    constructor() {
        this.initializeElements();
        this.bindEvents();
        this.loadHistory();
        this.currentQuery = '';
        this.baseUrl = window.location.origin;
        this.todos = [];
        this.currentTab = 'search';
        this.lastSearchResult = null; // 最後の検索結果を保存
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
        this.editorTab = document.getElementById('editorTab');
        this.chunksTab = document.getElementById('chunksTab');

        // TODO要素
        this.extractTodosBtn = document.getElementById('extractTodosBtn');
        this.statusFilter = document.getElementById('statusFilter');
        this.todoInput = document.getElementById('todoInput');
        this.prioritySelect = document.getElementById('prioritySelect');
        this.addTodoBtn = document.getElementById('addTodoBtn');
        this.todoLoadingIndicator = document.getElementById('todoLoadingIndicator');
        this.todoList = document.getElementById('todoList');

        // エディタ要素
        this.fileTree = document.getElementById('fileTree');
        this.newFileBtn = document.getElementById('newFileBtn');
        this.saveFileBtn = document.getElementById('saveFileBtn');
        this.popoutEditorBtn = document.getElementById('popoutEditorBtn');
        this.currentFilePath = document.getElementById('currentFilePath');
        this.fileStatus = document.getElementById('fileStatus');
        this.markdownEditor = document.getElementById('markdownEditor');
        this.markdownPreview = document.getElementById('markdownPreview');
        this.previewContent = document.getElementById('previewContent');
        this.toolbarBtns = document.querySelectorAll('.toolbar-btn');

        // チャンク可視化要素
        this.chunkFileSelect = document.getElementById('chunkFileSelect');
        this.analyzeChunksBtn = document.getElementById('analyzeChunksBtn');
        this.refreshIndexBtn = document.getElementById('refreshIndexBtn');
        this.chunksLoadingIndicator = document.getElementById('chunksLoadingIndicator');
        this.totalChunks = document.getElementById('totalChunks');
        this.headerChunks = document.getElementById('headerChunks');
        this.contentChunks = document.getElementById('contentChunks');
        this.chunksList = document.getElementById('chunksList');
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

        // エディタイベント
        this.newFileBtn.addEventListener('click', () => this.createNewFile());
        this.saveFileBtn.addEventListener('click', () => this.saveCurrentFile());
        this.popoutEditorBtn.addEventListener('click', () => this.popoutEditor());
        this.markdownEditor.addEventListener('input', () => this.updatePreview());
        this.toolbarBtns.forEach(btn => {
            btn.addEventListener('click', (e) => this.handleToolbarAction(e.target.dataset.action));
        });

        // チャンク可視化イベント
        this.chunkFileSelect.addEventListener('change', () => this.enableAnalyzeButton());
        this.analyzeChunksBtn.addEventListener('click', () => this.analyzeSelectedFile());
        this.refreshIndexBtn.addEventListener('click', () => this.refreshIndex());
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
        // 検索結果を保存
        this.lastSearchResult = result;
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

            // ソースタイプに応じたアイコンとヘッダー
            const typeIcon = source.type === 'header' ? '📑' : '📄';
            const typeLabel = source.type === 'header' ? 'ヘッダー' : 'コンテンツ';

            const header = document.createElement('div');
            header.className = 'source-header';
            header.innerHTML = `${typeIcon} ${source.header || 'セクション ' + (index + 1)} (${typeLabel})`;

            const content = document.createElement('div');
            content.className = 'source-content';
            content.textContent = source.content;

            // ファイル情報を整理 - バックエンドとの整合性を保つ
            const filePath = source.doc_id || '';
            const fileDisplayName = this.getFileNameFromPath(filePath);

            // スコアの表示を改善
            const score = source.score || 0;
            const scorePercentage = (score * 100).toFixed(1);
            const scoreDisplay = score > 0 ? `${scorePercentage}%` : 'N/A';

            const meta = document.createElement('div');
            meta.className = 'source-meta';

            meta.innerHTML = `
                📁 <a href="#" class="source-link" data-file-path="${filePath}" onclick="ragInterface.openFileInEditor('${filePath}', event)">${fileDisplayName}</a> | 
                🎯 関連度: ${scoreDisplay} | 
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

        // 初期タブでTODOを読み込み
        this.loadTodos();

        // エディタタブでファイル一覧を読み込み
        this.loadFileList();
    }

    switchTab(tabName) {
        // 全タブを非表示
        this.searchTab.classList.remove('active');
        this.todosTab.classList.remove('active');
        this.editorTab.classList.remove('active');
        this.chunksTab.classList.remove('active');

        // 全タブボタンを非アクティブ
        this.navTabs.forEach(tab => tab.classList.remove('active'));

        // 選択されたタブをアクティブ
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');

        // 対応するコンテンツを表示
        switch (tabName) {
            case 'search':
                this.searchTab.classList.add('active');
                this.currentTab = 'search';
                // 最後の検索結果を復元
                if (this.lastSearchResult) {
                    this.displayResults(this.lastSearchResult);
                }
                break;
            case 'todos':
                this.todosTab.classList.add('active');
                this.currentTab = 'todos';
                this.loadTodos();
                break;
            case 'editor':
                this.editorTab.classList.add('active');
                this.currentTab = 'editor';
                this.loadFileList();
                break;
            case 'chunks':
                this.chunksTab.classList.add('active');
                this.currentTab = 'chunks';
                this.loadFileListForChunks();
                break;
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
                        <span>ソース: <a href="#" class="source-link" data-file-path="${todo.source_file}" onclick="ragInterface.openFileInEditor('${todo.source_file}', event)">${this.getFileNameFromPath(todo.source_file)}</a> > ${todo.source_section}</span>
                        <span>作成: ${new Date(todo.created_at).toLocaleString('ja-JP')}</span>
                    </div>
                </div>
                <div class="todo-actions">
                    <select class="priority-change-select" onchange="ragInterface.changeTodoPriority('${todo.id}', this.value)">
                        <option value="low" ${todo.priority === 'low' ? 'selected' : ''}>低</option>
                        <option value="medium" ${todo.priority === 'medium' ? 'selected' : ''}>中</option>
                        <option value="high" ${todo.priority === 'high' ? 'selected' : ''}>高</option>
                    </select>
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

    async changeTodoPriority(todoId, newPriority) {
        const todo = this.todos.find(t => t.id === todoId);
        if (!todo) return;

        if (newPriority !== todo.priority) {
            await this.updateTodo(todoId, { priority: newPriority });
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

    getFileNameFromPath(filePath) {
        if (!filePath) return '';
        const parts = filePath.split(/[/\\]/);
        return parts[parts.length - 1] || filePath;
    }

    openFileInEditor(filePath, event) {
        event.preventDefault();

        // エディタタブに切り替え
        this.switchTab('editor');

        // ファイルを選択
        this.selectFile(filePath);
    }

    showTodoLoading() {
        this.todoLoadingIndicator.style.display = 'block';
    }

    hideTodoLoading() {
        this.todoLoadingIndicator.style.display = 'none';
    }

    // エディタ機能
    async loadFileList() {
        try {
            const response = await fetch(`${this.baseUrl}/api/files`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.populateFileTree(data.files);
            this.populateChunkFileSelect(data.files);
        } catch (error) {
            console.error('ファイル一覧の読み込みに失敗:', error);
            this.setFileStatus('ファイル一覧の読み込みに失敗しました', 'error');
        }
    }

    populateFileTree(files) {
        this.fileTree.innerHTML = '';

        if (!files || files.length === 0) {
            this.fileTree.innerHTML = '<div class="no-files">ファイルが見つかりません</div>';
            return;
        }

        // フォルダ別にファイルを整理
        const folders = {};
        files.forEach(file => {
            const folder = file.folder || 'その他';
            if (!folders[folder]) {
                folders[folder] = [];
            }
            folders[folder].push(file);
        });

        // フォルダとファイルを表示
        Object.keys(folders).sort().forEach(folderName => {
            const folderDiv = document.createElement('div');
            folderDiv.className = 'file-folder';

            const folderHeader = document.createElement('div');
            folderHeader.className = 'folder-header';
            folderHeader.innerHTML = `<span class="folder-icon">📁</span> ${folderName}`;

            const filesList = document.createElement('div');
            filesList.className = 'files-list';

            folders[folderName].forEach(file => {
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                fileItem.innerHTML = `
                    <span class="file-icon">📄</span>
                    <span class="file-name">${file.name}</span>
                    <span class="file-size">${this.formatFileSize(file.size)}</span>
                `;
                fileItem.addEventListener('click', () => this.selectFile(file.path));
                filesList.appendChild(fileItem);
            });

            folderDiv.appendChild(folderHeader);
            folderDiv.appendChild(filesList);
            this.fileTree.appendChild(folderDiv);
        });
    }

    populateChunkFileSelect(files) {
        this.chunkFileSelect.innerHTML = '<option value="">ファイルを選択...</option>';
        files.forEach(file => {
            const option = document.createElement('option');
            option.value = file.path;
            option.textContent = `${file.folder}/${file.name}`;
            this.chunkFileSelect.appendChild(option);
        });
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    selectFile(filePath) {
        this.selectedFilePath = filePath;
        this.loadSelectedFile();

        // 選択されたファイルをハイライト
        const fileItems = this.fileTree.querySelectorAll('.file-item');
        fileItems.forEach(item => item.classList.remove('selected'));
        const selectedItem = Array.from(fileItems).find(item =>
            item.querySelector('.file-name').textContent === this.getFileNameFromPath(filePath)
        );
        if (selectedItem) {
            selectedItem.classList.add('selected');
        }
    }

    async loadSelectedFile() {
        const filePath = this.selectedFilePath;
        if (!filePath) {
            this.clearEditor();
            return;
        }

        try {
            this.setFileStatus('読み込み中...', 'loading');
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(filePath)}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.markdownEditor.value = data.content;
            this.currentFilePath.textContent = data.path;
            this.updatePreview();
            this.saveFileBtn.disabled = false;
            this.setFileStatus(`読み込み完了 (${this.formatFileSize(data.size)})`, 'success');
        } catch (error) {
            console.error('ファイル読み込みエラー:', error);
            this.setFileStatus(`読み込みエラー: ${error.message}`, 'error');
        }
    }

    clearEditor() {
        this.markdownEditor.value = '';
        this.previewContent.innerHTML = 'ここにプレビューが表示されます';
        this.currentFilePath.textContent = 'ファイルが選択されていません';
        this.saveFileBtn.disabled = true;
        this.selectedFilePath = null;

        // ファイル選択をクリア
        const fileItems = this.fileTree.querySelectorAll('.file-item');
        fileItems.forEach(item => item.classList.remove('selected'));

        this.setFileStatus('', '');
    }

    updatePreview() {
        const markdown = this.markdownEditor.value;
        if (!markdown.trim()) {
            this.previewContent.innerHTML = 'ここにプレビューが表示されます';
            return;
        }

        // 簡単なMarkdownプレビュー（本格的な場合はmarkdown-itライブラリなどを使用）
        let html = markdown
            .replace(/^# (.*$)/gim, '<h1>$1</h1>')
            .replace(/^## (.*$)/gim, '<h2>$1</h2>')
            .replace(/^### (.*$)/gim, '<h3>$1</h3>')
            .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
            .replace(/\*(.*)\*/gim, '<em>$1</em>')
            .replace(/`(.*)`/gim, '<code>$1</code>')
            .replace(/^- (.*$)/gim, '<li>$1</li>')
            .replace(/\n/gim, '<br>');

        // リストをul要素で囲む
        html = html.replace(/(<li>.*?<\/li>)/gs, '<ul>$1</ul>');

        this.previewContent.innerHTML = html;
    }

    async saveCurrentFile() {
        const filePath = this.selectedFilePath;
        if (!filePath) {
            alert('ファイルが選択されていません');
            return;
        }

        try {
            this.setFileStatus('保存中...', 'loading');
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(filePath)}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content: this.markdownEditor.value
                })
            });

            const data = await response.json();
            if (data.error) {
                throw new Error(data.error);
            }

            this.setFileStatus(`保存完了 (${this.formatFileSize(data.size)})`, 'success');

            // ファイルツリーを更新
            this.loadFileList();
        } catch (error) {
            console.error('ファイル保存エラー:', error);
            this.setFileStatus(`保存エラー: ${error.message}`, 'error');
        }
    }

    createNewFile() {
        const fileName = prompt('ファイル名を入力してください (例: memo.md):');
        if (!fileName) return;

        // .md拡張子を自動追加
        const fullFileName = fileName.endsWith('.md') ? fileName : fileName + '.md';

        // フォルダの指定があるかチェック
        const filePath = fullFileName.includes('/') ? fullFileName : `data/${fullFileName}`;

        this.selectedFilePath = filePath;
        this.markdownEditor.value = `# ${fileName.replace('.md', '')}\n\n`;
        this.currentFilePath.textContent = filePath;
        this.updatePreview();
        this.saveFileBtn.disabled = false;
        this.setFileStatus('新規ファイル（未保存）', 'warning');

        // ファイル選択をクリア
        const fileItems = this.fileTree.querySelectorAll('.file-item');
        fileItems.forEach(item => item.classList.remove('selected'));
    }



    handleToolbarAction(action) {
        const textarea = this.markdownEditor;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const selectedText = textarea.value.substring(start, end);
        let replacement = '';

        switch (action) {
            case 'bold':
                replacement = `**${selectedText || 'テキスト'}**`;
                break;
            case 'italic':
                replacement = `*${selectedText || 'テキスト'}*`;
                break;
            case 'header':
                replacement = `## ${selectedText || 'ヘッダー'}`;
                break;
            case 'list':
                replacement = `- ${selectedText || 'リスト項目'}`;
                break;
            case 'code':
                replacement = `\`${selectedText || 'コード'}\``;
                break;
        }

        textarea.value = textarea.value.substring(0, start) + replacement + textarea.value.substring(end);
        textarea.focus();
        textarea.setSelectionRange(start, start + replacement.length);
        this.updatePreview();
    }

    setFileStatus(message, type) {
        this.fileStatus.textContent = message;
        this.fileStatus.className = `file-status ${type}`;
    }

    popoutEditor() {
        const currentContent = this.markdownEditor.value;
        const currentFilePath = this.selectedFilePath || 'untitled.md';
        const fileName = this.getFileNameFromPath(currentFilePath);

        // 新しいウィンドウを開く
        const popupWindow = window.open('', `editor_${Date.now()}`,
            'width=1200,height=800,scrollbars=yes,resizable=yes,toolbar=no,menubar=no,location=no,status=no');

        if (!popupWindow) {
            alert('ポップアップがブロックされました。ブラウザの設定でポップアップを許可してください。');
            return;
        }

        // ポップアウトウィンドウのHTML
        popupWindow.document.write(`
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>メモエディタ - ${fileName}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f5f5f5;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        
        .editor-header {
            background: #2c3e50;
            color: white;
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .editor-title {
            font-size: 18px;
            font-weight: 500;
        }
        
        .editor-controls {
            display: flex;
            gap: 10px;
        }
        
        .control-btn {
            background: #3498db;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: background-color 0.3s;
        }
        
        .control-btn:hover {
            background: #2980b9;
        }
        
        .control-btn:disabled {
            background: #95a5a6;
            cursor: not-allowed;
        }
        
                 .editor-container {
             flex: 1;
             display: flex;
             flex-direction: column;
             height: calc(100vh - 70px);
         }
         
         .pane-header {
             background: #34495e;
             color: white;
             padding: 10px 15px;
             font-weight: 500;
             font-size: 14px;
         }
         
         .editor-textarea {
             flex: 1;
             border: none;
             padding: 20px;
             font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
             font-size: 14px;
             line-height: 1.6;
             resize: none;
             outline: none;
             background: white;
         }
        
        .status-bar {
            background: #ecf0f1;
            padding: 5px 15px;
            font-size: 12px;
            color: #7f8c8d;
            border-top: 1px solid #ddd;
        }
    </style>
</head>
<body>
    <div class="editor-header">
        <div class="editor-title">📝 ${fileName}</div>
        <div class="editor-controls">
            <button class="control-btn" onclick="saveToParent()">保存</button>
            <button class="control-btn" onclick="window.close()">閉じる</button>
        </div>
    </div>
    
         <div class="editor-container">
         <div class="pane-header">✏️ エディタ</div>
         <textarea class="editor-textarea" id="popupEditor" placeholder="Markdownを入力してください...">${currentContent}</textarea>
     </div>
    
    <div class="status-bar">
        <span id="statusText">準備完了</span>
    </div>

         <script>
         const editor = document.getElementById('popupEditor');
         const statusText = document.getElementById('statusText');
         
         function saveToParent() {
             if (window.opener && !window.opener.closed) {
                 // 親ウィンドウのエディタに内容を同期
                 window.opener.ragInterface.markdownEditor.value = editor.value;
                 window.opener.ragInterface.updatePreview();
                 statusText.textContent = '保存しました';
                 setTimeout(() => {
                     statusText.textContent = '準備完了';
                 }, 2000);
             } else {
                 alert('親ウィンドウが見つかりません');
             }
         }
         
         // 親ウィンドウとの同期
         setInterval(() => {
             if (window.opener && !window.opener.closed) {
                 const parentContent = window.opener.ragInterface.markdownEditor.value;
                 if (parentContent !== editor.value) {
                     editor.value = parentContent;
                 }
             }
         }, 1000);
         
         // ウィンドウが閉じられる前に確認
         window.addEventListener('beforeunload', (e) => {
             if (window.opener && !window.opener.closed) {
                 saveToParent();
             }
         });
     </script>
</body>
</html>
        `);

        popupWindow.document.close();
        popupWindow.focus();
    }

    // チャンク可視化機能
    loadFileListForChunks() {
        this.loadFileList(); // ファイル一覧は共通
    }

    enableAnalyzeButton() {
        this.analyzeChunksBtn.disabled = !this.chunkFileSelect.value;
    }

    async analyzeSelectedFile() {
        const filePath = this.chunkFileSelect.value;
        if (!filePath) return;

        try {
            this.showChunksLoading();
            const response = await fetch(`${this.baseUrl}/api/chunks/analyze/${encodeURIComponent(filePath)}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.displayChunksAnalysis(data);
        } catch (error) {
            console.error('チャンク分析エラー:', error);
            this.displayChunksError(error.message);
        } finally {
            this.hideChunksLoading();
        }
    }

    displayChunksAnalysis(data) {
        // 統計情報を更新
        this.totalChunks.textContent = data.total_chunks;
        this.headerChunks.textContent = data.header_chunks;
        this.contentChunks.textContent = data.content_chunks;

        // チャンクリストを表示
        this.chunksList.innerHTML = '';

        if (data.chunks.length === 0) {
            this.chunksList.innerHTML = '<div class="empty-chunks">チャンクが見つかりませんでした</div>';
            return;
        }

        data.chunks.forEach((chunk, index) => {
            const chunkItem = document.createElement('div');
            chunkItem.className = `chunk-item chunk-${chunk.type}`;

            const typeIcon = chunk.type === 'header' ? '📑' : '📄';
            const header = chunk.metadata.header || `チャンク ${index + 1}`;

            chunkItem.innerHTML = `
                <div class="chunk-header">
                    <span class="chunk-type">${typeIcon} ${chunk.type}</span>
                    <span class="chunk-title">${header}</span>
                    <span class="chunk-level">H${chunk.metadata.level}</span>
                </div>
                <div class="chunk-content">
                    <div class="chunk-preview">${chunk.preview}</div>
                    <div class="chunk-meta">
                        <span>長さ: ${chunk.text_length}文字</span>
                        <span>セクション: ${chunk.metadata.section_id}</span>
                        <span>ファイル: ${chunk.metadata.file_name}</span>
                        ${chunk.metadata.folder_name ? `<span>フォルダ: ${chunk.metadata.folder_name}</span>` : ''}
                    </div>
                </div>
            `;

            // クリックで詳細表示
            chunkItem.addEventListener('click', () => {
                this.showChunkDetails(chunk);
            });

            this.chunksList.appendChild(chunkItem);
        });
    }

    showChunkDetails(chunk) {
        const modal = document.createElement('div');
        modal.className = 'chunk-modal';
        modal.innerHTML = `
            <div class="chunk-modal-content">
                <div class="chunk-modal-header">
                    <h3>${chunk.metadata.header || 'チャンク詳細'}</h3>
                    <button class="chunk-modal-close">&times;</button>
                </div>
                <div class="chunk-modal-body">
                    <div class="chunk-full-text">${chunk.text}</div>
                    <div class="chunk-metadata">
                        <h4>メタデータ</h4>
                        <pre>${JSON.stringify(chunk.metadata, null, 2)}</pre>
                    </div>
                </div>
            </div>
        `;

        modal.querySelector('.chunk-modal-close').addEventListener('click', () => {
            document.body.removeChild(modal);
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        });

        document.body.appendChild(modal);
    }

    displayChunksError(message) {
        this.chunksList.innerHTML = `<div class="chunks-error">エラー: ${message}</div>`;
        this.totalChunks.textContent = '-';
        this.headerChunks.textContent = '-';
        this.contentChunks.textContent = '-';
    }

    async refreshIndex() {
        if (!confirm('インデックスを更新しますか？時間がかかる場合があります。')) return;

        try {
            this.showChunksLoading();
            const response = await fetch(`${this.baseUrl}/api/index/refresh`, {
                method: 'POST'
            });

            const data = await response.json();
            if (data.error) {
                throw new Error(data.error);
            }

            alert('インデックスが更新されました');
        } catch (error) {
            console.error('インデックス更新エラー:', error);
            alert(`インデックス更新エラー: ${error.message}`);
        } finally {
            this.hideChunksLoading();
        }
    }

    showChunksLoading() {
        this.chunksLoadingIndicator.style.display = 'block';
        this.analyzeChunksBtn.disabled = true;
        this.refreshIndexBtn.disabled = true;
    }

    hideChunksLoading() {
        this.chunksLoadingIndicator.style.display = 'none';
        this.analyzeChunksBtn.disabled = false;
        this.refreshIndexBtn.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const ragInterface = new RAGInterface();

    window.ragInterface = ragInterface;
});