class RAGInterface {
    constructor() {
        this.initializeElements();
        this.bindEvents();
        this.loadHistory();
        this.currentQuery = '';
        this.baseUrl = window.location.origin;
        this.todos = [];
        this.lastSearchResult = null; // 最後の検索結果を保存
        this.selectedTodoForSearch = null; // 検索に挿入するTODO
        this.currentDocumentPath = null; // 現在表示中のドキュメント
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
        this.insertTodoToSearchBtn = document.getElementById('insertTodoToSearchBtn');

        // TODO要素
        this.extractTodosBtn = document.getElementById('extractTodosBtn');
        this.statusFilter = document.getElementById('statusFilter');
        this.todoInput = document.getElementById('todoInput');
        this.prioritySelect = document.getElementById('prioritySelect');
        this.dueDateInput = document.getElementById('dueDateInput');
        this.addTodoBtn = document.getElementById('addTodoBtn');
        this.todoLoadingIndicator = document.getElementById('todoLoadingIndicator');
        this.todoList = document.getElementById('todoList');

        // ファイルエクスプローラー要素
        this.fileTree = document.getElementById('fileTree');
        this.newFileBtn = document.getElementById('newFileBtn');
        this.newFolderBtn = document.getElementById('newFolderBtn');
        this.refreshFilesBtn = document.getElementById('refreshFilesBtn');
        this.fileSearchInput = document.getElementById('fileSearchInput');
        this.documentViewer = document.getElementById('documentViewer');
        this.documentTitle = document.getElementById('documentTitle');
        this.documentContent = document.getElementById('documentContent');
        this.editDocumentBtn = document.getElementById('editDocumentBtn');
        this.closeDocumentBtn = document.getElementById('closeDocumentBtn');

        // Fancytree instance
        this.jsTreeInstance = null;
        this.allFiles = [];

    }

    bindEvents() {
        // RAGイベント
        this.searchButton.addEventListener('click', () => this.handleSearch());
        this.queryInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.handleSearch();
            }
        });
        this.insertTodoToSearchBtn.addEventListener('click', () => this.insertTodoToSearch());

        // TODOイベント
        this.extractTodosBtn.addEventListener('click', () => this.extractTodos());
        this.statusFilter.addEventListener('change', () => this.filterTodos());
        this.addTodoBtn.addEventListener('click', () => this.addTodo());
        this.todoInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.addTodo();
            }
        });

        // ファイルエクスプローラーイベント
        this.newFileBtn.addEventListener('click', () => this.createNewFile());
        this.newFolderBtn.addEventListener('click', () => this.createNewFolder());
        this.refreshFilesBtn.addEventListener('click', () => this.loadFileList());
        this.editDocumentBtn.addEventListener('click', () => this.editCurrentDocument());
        this.closeDocumentBtn.addEventListener('click', () => this.closeDocumentViewer());
        this.fileSearchInput.addEventListener('input', (e) => this.searchFiles(e.target.value));

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

            // チャンクコンテンツをBase64エンコードして安全に渡す
            const encodedChunkContent = btoa(encodeURIComponent(source.content));

            meta.innerHTML = `
                📁 <a href="#" class="source-link" data-file-path="${filePath}" data-chunk-content="${encodedChunkContent}" onclick="ragInterface.openFileWithChunkHighlight('${filePath}', '${encodedChunkContent}', event)">${fileDisplayName}</a> | 
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

    // 初期化処理
    initialize() {
        // TODOを読み込み
        this.loadTodos();
        // ファイル一覧を読み込み
        this.loadFileList();
    }

    // TODO検索窓挿入機能
    insertTodoToSearch() {
        if (this.selectedTodoForSearch) {
            this.queryInput.value = this.selectedTodoForSearch.content;
            this.queryInput.focus();
        } else {
            alert('検索に挿入するTODOを選択してください。');
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
        const dueDate = this.dueDateInput.value || null;

        try {
            const requestBody = {
                content: content,
                priority: priority
            };

            if (dueDate) {
                requestBody.due_date = dueDate;
            }

            const response = await fetch(`${this.baseUrl}/api/todos`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody)
            });

            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.todoInput.value = '';
            this.dueDateInput.value = '';
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
        let filteredTodos = statusFilter ?
            this.todos.filter(todo => todo.status === statusFilter) :
            this.todos;

        // 新しい順（updated_atの降順）でソート
        filteredTodos.sort((a, b) => {
            const dateA = new Date(a.updated_at || a.created_at);
            const dateB = new Date(b.updated_at || b.created_at);
            return dateB - dateA; // 降順
        });

        if (filteredTodos.length === 0) {
            this.todoList.innerHTML = '<div class="empty-todos">メモからTODOを抽出するか、手動で追加してください。</div>';
            return;
        }

        this.todoList.innerHTML = '';

        filteredTodos.forEach(todo => {
            const todoItem = document.createElement('div');
            todoItem.className = `todo-item priority-${todo.priority} status-${todo.status}`;

            // 締切情報の処理
            let dueDateDisplay = '';
            if (todo.due_date) {
                const dueDate = new Date(todo.due_date);
                const today = new Date();
                const diffDays = Math.ceil((dueDate - today) / (1000 * 60 * 60 * 24));

                let dueDateClass = '';
                if (diffDays < 0) {
                    dueDateClass = 'overdue';
                } else if (diffDays <= 1) {
                    dueDateClass = 'due-soon';
                } else if (diffDays <= 7) {
                    dueDateClass = 'due-this-week';
                }

                dueDateDisplay = `<span class="due-date ${dueDateClass}">締切: ${dueDate.toLocaleDateString('ja-JP')}</span>`;
            }

            todoItem.innerHTML = `
                <input type="checkbox" class="todo-checkbox" ${todo.status === 'completed' ? 'checked' : ''} 
                       onchange="ragInterface.toggleTodoStatus('${todo.id}')">
                <div class="todo-content">
                    <div class="todo-text ${todo.status === 'completed' ? 'completed' : ''}">${todo.content}</div>
                    <div class="todo-meta">
                        <span class="status-badge ${todo.status}">${this.getStatusText(todo.status)}</span>
                        <span class="priority-badge ${todo.priority}">${this.getPriorityText(todo.priority)}</span>
                        ${dueDateDisplay}
                        <span>ソース: <a href="#" class="source-link" data-file-path="${todo.source_file}" onclick="ragInterface.openFileInDocumentViewer('${todo.source_file}', event)">${this.getFileNameFromPath(todo.source_file)}</a> > ${todo.source_section}</span>
                        <button class="select-todo-btn" onclick="ragInterface.selectTodoForSearch('${todo.id}')" title="検索窓に挿入">→検索</button>
                        <span>作成: ${new Date(todo.created_at).toLocaleString('ja-JP')}</span>
                        ${todo.updated_at !== todo.created_at ? `<span>更新: ${new Date(todo.updated_at).toLocaleString('ja-JP')}</span>` : ''}
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

    selectTodoForSearch(todoId) {
        const todo = this.todos.find(t => t.id === todoId);
        if (todo) {
            this.selectedTodoForSearch = todo;
            // 他の選択を解除
            document.querySelectorAll('.select-todo-btn').forEach(btn => {
                btn.classList.remove('selected');
                btn.textContent = '→検索';
            });
            // 選択されたボタンをハイライト
            event.target.classList.add('selected');
            event.target.textContent = '選択中';

            // 検索ボタンを有効化
            this.insertTodoToSearchBtn.disabled = false;
        }
    }

    openFileInDocumentViewer(filePath, event) {
        event.preventDefault();
        this.loadFileContent(filePath);
    }

    openFileWithChunkHighlight(filePath, encodedChunkContent, event) {
        event.preventDefault();

        // Base64デコードしてチャンクコンテンツを復元
        const chunkContent = decodeURIComponent(atob(encodedChunkContent));

        this.loadFileContentWithHighlight(filePath, chunkContent);
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

            this.allFiles = data.files;
            this.populateExplorer(data.files);
        } catch (error) {
            console.error('ファイル一覧の読み込みに失敗:', error);
            this.showFileTreeError('ファイル一覧の読み込みに失敗しました');
        }
    }

    populateExplorer(files) {
        if (!files || files.length === 0) {
            this.fileTree.innerHTML = '<div class="no-files">ファイルが見つかりません</div>';
            return;
        }

        // ファイル構造を構築
        const tree = this.buildFileTree(files);

        // エクスプローラーHTMLを生成
        this.fileTree.innerHTML = this.generateExplorerHTML(tree);

        // イベントリスナーを設定
        this.setupExplorerEvents();
    }

    buildFileTree(files) {
        const tree = {};

        files.forEach(file => {
            const pathParts = file.path.split('/').filter(part => part.length > 0);
            let currentLevel = tree;

            // フォルダ部分を処理
            for (let i = 0; i < pathParts.length - 1; i++) {
                const folderName = pathParts[i];
                if (!currentLevel[folderName]) {
                    currentLevel[folderName] = {
                        type: 'folder',
                        children: {}
                    };
                }
                currentLevel = currentLevel[folderName].children;
            }

            // ファイルを追加
            const fileName = pathParts[pathParts.length - 1];
            currentLevel[fileName] = {
                type: 'file',
                data: file
            };
        });

        return tree;
    }

    generateExplorerHTML(tree, level = 0) {
        let html = '';

        Object.keys(tree).sort().forEach(key => {
            const item = tree[key];
            const indent = level * 20;

            if (item.type === 'folder') {
                const hasChildren = Object.keys(item.children).length > 0;

                html += `
                    <details class="folder-details" data-folder="${key}">
                        <summary class="folder-summary" style="padding-left: ${indent}px">
                            <i class="fas fa-folder folder-icon"></i>
                            <span class="folder-name">${key}</span>
                        </summary>
                        <div class="folder-content">
                            ${hasChildren ? this.generateExplorerHTML(item.children, level + 1) : ''}
                        </div>
                    </details>
                `;
            } else {
                const fileIcon = this.getFileIcon(key);
                const fileSize = this.formatFileSize(item.data.size);

                html += `
                    <div class="file-item" data-path="${item.data.path}" style="padding-left: ${indent + 20}px">
                        <i class="${fileIcon} file-icon"></i>
                        <span class="file-name">${key}</span>
                        <span class="file-size">(${fileSize})</span>
                    </div>
                `;
            }
        });

        return html;
    }

    setupExplorerEvents() {
        // 全てのdetails要素を確実に閉じた状態に設定
        this.fileTree.querySelectorAll('details').forEach(details => {
            details.removeAttribute('open');
            details.open = false;
        });

        // ファイルクリック処理
        this.fileTree.addEventListener('click', (e) => {
            const fileItem = e.target.closest('.file-item');
            if (fileItem) {
                // 既存の選択をクリア
                this.fileTree.querySelectorAll('.file-item.selected').forEach(item => {
                    item.classList.remove('selected');
                });

                // 新しい選択を設定
                fileItem.classList.add('selected');

                // ファイルを読み込み
                const filePath = fileItem.dataset.path;
                this.loadFileContent(filePath);
            }
        });

        // ファイルダブルクリック処理
        this.fileTree.addEventListener('dblclick', (e) => {
            const fileItem = e.target.closest('.file-item');
            if (fileItem) {
                const filePath = fileItem.dataset.path;
                this.openPopoutEditor(filePath);
            }
        });

        // フォルダの展開/折りたたみ処理
        this.fileTree.addEventListener('toggle', (e) => {
            if (e.target.classList.contains('folder-details')) {
                const icon = e.target.querySelector('.folder-icon');
                if (e.target.open) {
                    // 展開時
                    icon.className = 'fas fa-folder-open folder-icon';
                    console.log(`フォルダ展開: ${e.target.dataset.folder}`);
                } else {
                    // 折りたたみ時
                    icon.className = 'fas fa-folder folder-icon';
                    console.log(`フォルダ折りたたみ: ${e.target.dataset.folder}`);
                }
            }
        });

        // 初期状態確認
        const folderCount = this.fileTree.querySelectorAll('details').length;
        const openCount = this.fileTree.querySelectorAll('details[open]').length;
        console.log(`フォルダ総数: ${folderCount}, 開いているフォルダ: ${openCount}`);
    }

    getFileIcon(fileName) {
        const extension = fileName.split('.').pop().toLowerCase();

        switch (extension) {
            case 'md':
            case 'markdown':
                return 'fab fa-markdown';
            case 'txt':
                return 'fas fa-file-alt';
            case 'json':
                return 'fas fa-file-code';
            case 'py':
                return 'fab fa-python';
            case 'js':
                return 'fab fa-js-square';
            case 'pdf':
                return 'fas fa-file-pdf';
            case 'jpg':
            case 'jpeg':
            case 'png':
            case 'gif':
                return 'fas fa-file-image';
            default:
                return 'fas fa-file';
        }
    }



    showFileTreeError(message) {
        this.fileTree.innerHTML = `<div class="file-tree-error">${message}</div>`;
    }



    async loadFileContent(filePath) {
        if (!filePath) return;

        try {
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(filePath)}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.currentDocumentPath = filePath;
            this.documentTitle.textContent = this.getFileNameFromPath(filePath);

            // Markdownを簡易HTMLに変換
            const htmlContent = this.convertMarkdownToHtml(data.content);
            this.documentContent.innerHTML = htmlContent;

            this.documentViewer.style.display = 'block';

            // デフォルトメッセージを非表示
            const defaultContent = document.getElementById('defaultViewerContent');
            if (defaultContent) {
                defaultContent.style.display = 'none';
            }

            // ファイル選択状態を更新
            this.updateFileSelection(filePath);
        } catch (error) {
            console.error('ファイル読み込みエラー:', error);
            alert(`ファイル読み込みエラー: ${error.message}`);
        }
    }

    async loadFileContentWithHighlight(filePath, chunkContent) {
        if (!filePath) return;

        try {
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(filePath)}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.currentDocumentPath = filePath;
            this.documentTitle.textContent = `${this.getFileNameFromPath(filePath)} (該当箇所をハイライト)`;

            // チャンクをハイライトしてMarkdownを変換
            const highlightedContent = this.highlightChunkInMarkdown(data.content, chunkContent);
            const htmlContent = this.convertMarkdownToHtml(highlightedContent);
            this.documentContent.innerHTML = htmlContent;

            this.documentViewer.style.display = 'block';

            // デフォルトメッセージを非表示
            const defaultContent = document.getElementById('defaultViewerContent');
            if (defaultContent) {
                defaultContent.style.display = 'none';
            }

            // ファイル選択状態を更新
            this.updateFileSelection(filePath);

            // ハイライト箇所にスクロール
            setTimeout(() => {
                const highlightedElement = this.documentContent.querySelector('.chunk-highlight');
                if (highlightedElement) {
                    highlightedElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }, 100);

        } catch (error) {
            console.error('ファイル読み込みエラー:', error);
            alert(`ファイル読み込みエラー: ${error.message}`);
        }
    }

    highlightChunkInMarkdown(fullContent, chunkContent) {
        // チャンクコンテンツを正規化（空白や改行の違いを吸収）
        const normalizeText = (text) => text.replace(/\s+/g, ' ').trim();

        const normalizedChunk = normalizeText(chunkContent);
        const normalizedFull = normalizeText(fullContent);

        // 正規化されたテキストでチャンクの位置を見つける
        const chunkIndex = normalizedFull.indexOf(normalizedChunk);

        if (chunkIndex === -1) {
            // 正確なマッチが見つからない場合は、部分マッチを試す
            const chunkWords = normalizedChunk.split(' ');
            if (chunkWords.length > 3) {
                // 最初の数語でマッチを試す
                const partialChunk = chunkWords.slice(0, Math.min(5, chunkWords.length)).join(' ');
                const partialIndex = normalizedFull.indexOf(partialChunk);

                if (partialIndex !== -1) {
                    // 部分マッチが見つかった場合、元のテキストでハイライトマーカーを挿入
                    return this.insertHighlightInOriginalText(fullContent, partialChunk);
                }
            }

            // マッチしない場合はそのまま返す
            return fullContent;
        }

        // 元のテキストでハイライトマーカーを挿入
        return this.insertHighlightInOriginalText(fullContent, chunkContent);
    }

    insertHighlightInOriginalText(fullContent, targetText) {
        // より柔軟なマッチングのため、特殊文字をエスケープして正規表現を作成
        const escapeRegExp = (string) => string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

        // 空白の違いを許容する正規表現を作成
        const flexiblePattern = escapeRegExp(targetText).replace(/\\\s+/g, '\\s+');
        const regex = new RegExp(`(${flexiblePattern})`, 'i');

        const match = fullContent.match(regex);
        if (match) {
            const beforeText = fullContent.substring(0, match.index);
            const matchedText = match[0];
            const afterText = fullContent.substring(match.index + matchedText.length);

            return beforeText + `<span class="chunk-highlight">${matchedText}</span>` + afterText;
        }

        return fullContent;
    }

    convertMarkdownToHtml(markdown) {
        if (!markdown.trim()) return 'ファイルが空です';

        // markedライブラリを使用してMarkdownをHTMLに変換
        try {
            return marked.parse(markdown);
        } catch (error) {
            console.error('Markdown変換エラー:', error);
            return `<p>Markdown変換エラーが発生しました: ${error.message}</p>`;
        }
    }

    updateFileSelection(selectedPath) {
        const fileItems = this.fileTree.querySelectorAll('.file-item');
        fileItems.forEach(item => item.classList.remove('selected'));

        const selectedItem = Array.from(fileItems).find(item => {
            const fileName = item.querySelector('.file-name').textContent;
            return this.getFileNameFromPath(selectedPath) === fileName;
        });

        if (selectedItem) {
            selectedItem.classList.add('selected');
        }
    }

    closeDocumentViewer() {
        this.documentViewer.style.display = 'none';
        this.currentDocumentPath = null;

        // デフォルトメッセージを再表示
        const defaultContent = document.getElementById('defaultViewerContent');
        if (defaultContent) {
            defaultContent.style.display = 'block';
        }

        // ファイル選択をクリア
        const fileItems = this.fileTree.querySelectorAll('.file-item');
        fileItems.forEach(item => item.classList.remove('selected'));
    }

    editCurrentDocument() {
        if (this.currentDocumentPath) {
            this.openPopoutEditor(this.currentDocumentPath);
        }
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    async openPopoutEditor(existingFilePath = null, newFilePath = null, initialContent = '') {
        let currentContent = initialContent;
        let filePath = newFilePath || existingFilePath;
        let fileName = 'untitled.md';

        if (existingFilePath) {
            try {
                const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(existingFilePath)}`);
                const data = await response.json();

                if (data.error) {
                    throw new Error(data.error);
                }

                currentContent = data.content;
                filePath = existingFilePath;
                fileName = this.getFileNameFromPath(existingFilePath);
            } catch (error) {
                console.error('ファイル読み込みエラー:', error);
                alert(`ファイル読み込みエラー: ${error.message}`);
                return;
            }
        } else if (newFilePath) {
            fileName = this.getFileNameFromPath(newFilePath);
        }

        this.createPopoutWindow(fileName, filePath, currentContent);
    }

    async saveFileFromPopup(filePath, content) {
        try {
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(filePath)}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content: content
                })
            });

            const data = await response.json();
            if (data.error) {
                throw new Error(data.error);
            }

            // ファイルツリーを更新
            this.loadFileList();

            // ドキュメントビューアーが開いている場合は更新
            if (this.currentDocumentPath === filePath) {
                this.loadFileContent(filePath);
            }

            return { success: true, size: data.size };
        } catch (error) {
            console.error('ファイル保存エラー:', error);
            return { success: false, error: error.message };
        }
    }

    searchFiles(searchTerm) {
        if (this.jsTreeInstance) {
            this.jsTreeInstance.filterNodes(searchTerm, false);
        }
    }

    createNewFile() {
        const fileName = prompt('ファイル名を入力してください (例: memo.md):');
        if (!fileName) return;

        // .md拡張子を自動追加
        const fullFileName = fileName.endsWith('.md') ? fileName : fileName + '.md';

        // フォルダの指定があるかチェック
        const filePath = fullFileName.includes('/') ? fullFileName : `data/${fullFileName}`;

        // 新規ファイル用の別ウィンドウを開く
        this.openPopoutEditor(null, filePath, `# ${fileName.replace('.md', '')}\n\n`);
    }

    createNewFolder() {
        const folderName = prompt('フォルダ名を入力してください:');
        if (!folderName) return;

        const folderPath = `data/${folderName}`;
        // TODO: バックエンドAPIでフォルダ作成機能を実装
        alert('フォルダ作成機能は今後実装予定です');
    }

    createFileInFolder(folderPath) {
        const fileName = prompt('ファイル名を入力してください (例: memo.md):');
        if (!fileName) return;

        const fullFileName = fileName.endsWith('.md') ? fileName : fileName + '.md';
        const filePath = `${folderPath}/${fullFileName}`;

        this.openPopoutEditor(null, filePath, `# ${fileName.replace('.md', '')}\n\n`);
    }

    createFolderInFolder(parentPath) {
        const folderName = prompt('フォルダ名を入力してください:');
        if (!folderName) return;

        // TODO: バックエンドAPIでフォルダ作成機能を実装
        alert('フォルダ作成機能は今後実装予定です');
    }

    async deleteFile(filePath) {
        if (!confirm(`ファイル "${this.getFileNameFromPath(filePath)}" を削除しますか？`)) {
            return;
        }

        try {
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(filePath)}`, {
                method: 'DELETE'
            });

            const data = await response.json();
            if (data.error) {
                throw new Error(data.error);
            }

            alert('ファイルを削除しました');
            this.loadFileList();

            // 削除されたファイルが現在開いているファイルの場合、ビューアーを閉じる
            if (this.currentDocumentPath === filePath) {
                this.closeDocumentViewer();
            }
        } catch (error) {
            console.error('ファイル削除エラー:', error);
            alert(`ファイル削除エラー: ${error.message}`);
        }
    }

    async renameFileOrFolder(oldPath, newName) {
        try {
            // TODO: バックエンドAPIでファイル/フォルダ名前変更機能を実装
            alert('名前変更機能は今後実装予定です');
            this.loadFileList(); // 元に戻す
        } catch (error) {
            console.error('名前変更エラー:', error);
            alert(`名前変更エラー: ${error.message}`);
            this.loadFileList(); // 元に戻す
        }
    }




    createPopoutWindow(fileName, filePath, currentContent) {
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
            <button class="control-btn" onclick="saveFile()">保存</button>
            <button class="control-btn" onclick="window.close()">閉じる</button>
        </div>
    </div>
    
    <div class="editor-container">
         <div class="pane-header">✏️ エディタ</div>
         <textarea class="editor-textarea" id="popupEditor" placeholder="Markdownを入力してください...">${currentContent}</textarea>
     </div>
    
    <div class="status-bar">
        <span id="statusText">準備完了 - ${filePath || '新規ファイル'}</span>
    </div>

    <script>
         const editor = document.getElementById('popupEditor');
         const statusText = document.getElementById('statusText');
         const currentFilePath = '${filePath}';
         
         async function saveFile() {
             if (!currentFilePath) {
                 alert('ファイルパスが設定されていません');
                 return;
             }
             
             try {
                 statusText.textContent = '保存中...';
                 
                 if (window.opener && !window.opener.closed) {
                     const result = await window.opener.ragInterface.saveFileFromPopup(currentFilePath, editor.value);
                     
                     if (result.success) {
                         statusText.textContent = \`保存完了 (\${formatFileSize(result.size)})\`;
                         setTimeout(() => {
                             statusText.textContent = '準備完了 - ${filePath || '新規ファイル'}';
                         }, 3000);
                     } else {
                         statusText.textContent = \`保存エラー: \${result.error}\`;
                     }
                 } else {
                     alert('親ウィンドウが見つかりません');
                 }
             } catch (error) {
                 statusText.textContent = \`エラー: \${error.message}\`;
             }
         }
         
         function formatFileSize(bytes) {
             if (bytes === 0) return '0 B';
             const k = 1024;
             const sizes = ['B', 'KB', 'MB'];
             const i = Math.floor(Math.log(bytes) / Math.log(k));
             return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
         }
         
         // ウィンドウが閉じられる前に確認
         window.addEventListener('beforeunload', (e) => {
             if (editor.value.trim() && currentFilePath) {
                 e.preventDefault();
                 e.returnValue = '';
                 return '';
             }
         });
         
         // Ctrl+S で保存
         editor.addEventListener('keydown', (e) => {
             if (e.ctrlKey && e.key === 's') {
                 e.preventDefault();
                 saveFile();
             }
         });
     </script>
</body>
</html>
        `);

        popupWindow.document.close();
        popupWindow.focus();
    }

    async createNewFile(parentPath = '') {
        const fileName = prompt('新規ファイル名を入力してください:', 'new_file.md');
        if (!fileName) return;

        const fullPath = parentPath ? `${parentPath}/${fileName}` : fileName;

        try {
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(fullPath)}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content: ''
                })
            });

            if (response.ok) {
                this.loadFiles();
                this.openPopoutEditor(fullPath);
            } else {
                const error = await response.json();
                alert(`ファイル作成エラー: ${error.error}`);
            }
        } catch (error) {
            console.error('ファイル作成エラー:', error);
            alert(`ファイル作成エラー: ${error.message}`);
        }
    }

    async createNewFolder(parentPath = '') {
        const folderName = prompt('新規フォルダ名を入力してください:', 'new_folder');
        if (!folderName) return;

        const fullPath = parentPath ? `${parentPath}/${folderName}` : folderName;

        try {
            const response = await fetch(`${this.baseUrl}/api/folders`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    path: fullPath
                })
            });

            if (response.ok) {
                this.loadFiles();
            } else {
                const error = await response.json();
                alert(`フォルダ作成エラー: ${error.error}`);
            }
        } catch (error) {
            console.error('フォルダ作成エラー:', error);
            alert(`フォルダ作成エラー: ${error.message}`);
        }
    }

    async renameItem(node) {
        const currentPath = node.data.path;
        const currentName = node.text.replace(/<[^>]*>/g, '').trim(); // HTMLタグを除去
        const newName = prompt(`${node.type === 'folder' ? 'フォルダ' : 'ファイル'}の新しい名前を入力してください:`, currentName);

        if (!newName || newName === currentName) return;

        const pathParts = currentPath.split('/');
        pathParts[pathParts.length - 1] = newName;
        const newPath = pathParts.join('/');

        try {
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(currentPath)}/rename`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    new_name: newName
                })
            });

            if (response.ok) {
                this.loadFiles();
            } else {
                const error = await response.json();
                alert(`リネームエラー: ${error.error}`);
            }
        } catch (error) {
            console.error('リネームエラー:', error);
            alert(`リネームエラー: ${error.message}`);
        }
    }

    async deleteItem(node) {
        const itemType = node.type === 'folder' ? 'フォルダ' : 'ファイル';
        const nodeName = node.text.replace(/<[^>]*>/g, '').trim(); // HTMLタグを除去
        const confirmMessage = `${itemType} "${nodeName}" を削除しますか？`;

        if (!confirm(confirmMessage)) return;

        try {
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(node.data.path)}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.loadFiles();

                // もしビューアーで表示中だった場合は閉じる
                if (node.type !== 'folder' && this.documentViewer.style.display === 'block') {
                    const currentPath = document.getElementById('documentTitle').textContent;
                    if (currentPath === node.data.path) {
                        this.closeDocument();
                    }
                }
            } else {
                const error = await response.json();
                alert(`削除エラー: ${error.error}`);
            }
        } catch (error) {
            console.error('削除エラー:', error);
            alert(`削除エラー: ${error.message}`);
        }
    }

}

document.addEventListener('DOMContentLoaded', () => {
    const ragInterface = new RAGInterface();
    ragInterface.initialize();

    window.ragInterface = ragInterface;
});