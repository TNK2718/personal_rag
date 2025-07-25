class RAGInterface {
    constructor() {
        this.initializeElements();
        this.bindEvents();
        this.loadHistory();
        this.currentQuery = '';
        this.baseUrl = window.location.origin;
        this.todos = [];
        this.lastSearchResult = null; // 最後の検索結果を保存
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

        // TODO要素
        this.extractTodosBtn = document.getElementById('extractTodosBtn');
        this.statusFilter = document.getElementById('statusFilter');
        this.todoInput = document.getElementById('todoInput');
        this.prioritySelect = document.getElementById('prioritySelect');
        this.dueDateInput = document.getElementById('dueDateInput');
        this.addTodoBtn = document.getElementById('addTodoBtn');
        this.todoLoadingIndicator = document.getElementById('todoLoadingIndicator');
        this.todoList = document.getElementById('todoList');

        // ドキュメントビューアー要素
        this.documentViewer = document.getElementById('documentViewer');
        this.documentTitle = document.getElementById('documentTitle');
        this.documentContent = document.getElementById('documentContent');
        this.editDocumentBtn = document.getElementById('editDocumentBtn');
        this.closeDocumentBtn = document.getElementById('closeDocumentBtn');

        // js-fileexplorer要素
        this.fileExplorerElement = document.getElementById('fileExplorer');
        this.fileExplorer = null; // js-fileexplorerインスタンス
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

        // TODOイベント
        this.extractTodosBtn.addEventListener('click', () => this.extractTodos());
        this.statusFilter.addEventListener('change', () => this.filterTodos());
        this.addTodoBtn.addEventListener('click', () => this.addTodo());
        this.todoInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.addTodo();
            }
        });

        // ドキュメントビューアーイベント
        this.editDocumentBtn.addEventListener('click', () => this.editCurrentDocument());
        this.closeDocumentBtn.addEventListener('click', () => this.closeDocumentViewer());

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
        // 新規ファイル作成ボタンのイベントリスナーを追加（FileExplorer初期化前に1回だけ）
        if (!this.newFileButtonSetup) {
            this.setupNewFileButton();
            this.newFileButtonSetup = true;
        }
        // js-fileexplorerを初期化
        this.initializeFileExplorer();
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


    filterTodos() {
        this.renderTodos();
    }

    renderTodos() {
        const statusFilter = this.statusFilter.value;
        let filteredTodos = statusFilter ?
            this.todos.filter(todo => todo.status === statusFilter) :
            this.todos;

        // カスタムソート: 完了項目は下に、未完了は重要度と期限順
        filteredTodos.sort((a, b) => {
            // 完了状態でまず分ける（未完了が上、完了が下）
            if (a.status !== b.status) {
                if (a.status === 'completed') return 1;
                if (b.status === 'completed') return -1;
            }
            
            // 両方が未完了の場合：重要度順（高→中→低）、その後期限順
            if (a.status === 'pending' && b.status === 'pending') {
                // 重要度の優先度マップ
                const priorityOrder = { 'high': 3, 'medium': 2, 'low': 1 };
                const priorityDiff = (priorityOrder[b.priority] || 2) - (priorityOrder[a.priority] || 2);
                
                if (priorityDiff !== 0) {
                    return priorityDiff;
                }
                
                // 重要度が同じ場合は期限順（期限が近い順）
                const dateA = a.due_date ? new Date(a.due_date) : new Date('9999-12-31');
                const dateB = b.due_date ? new Date(b.due_date) : new Date('9999-12-31');
                return dateA - dateB; // 昇順（早い期限が上）
            }
            
            // 両方が完了の場合：更新日時の降順
            if (a.status === 'completed' && b.status === 'completed') {
                const dateA = new Date(a.updated_at || a.created_at);
                const dateB = new Date(b.updated_at || b.created_at);
                return dateB - dateA; // 降順
            }
            
            return 0;
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
                        <span>ソース: <a href="#" class="source-link todo-source-link" data-file-path="${todo.source_file}" data-source-section="${todo.source_section}">${this.getFileNameFromPath(todo.source_file)}</a> > ${todo.source_section}</span>
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
                    <button class="todo-action-btn search-btn" onclick="ragInterface.sendTodoToSearch('${todo.id}')" title="このTODOを検索窓に送る">→検索</button>
                </div>
            `;

            this.todoList.appendChild(todoItem);
        });

        // TODOソースリンクのイベントリスナーを追加
        this.setupTodoSourceLinks();
    }

    setupTodoSourceLinks() {
        const todoSourceLinks = document.querySelectorAll('.todo-source-link');
        todoSourceLinks.forEach(link => {
            link.addEventListener('click', (event) => {
                event.preventDefault();
                const filePath = link.getAttribute('data-file-path');
                const sourceSection = link.getAttribute('data-source-section');
                console.log('TODO ソースリンククリック:', filePath, 'セクション:', sourceSection);

                if (sourceSection && sourceSection !== 'manual') {
                    // セクション情報がある場合はハイライト表示
                    this.loadFileContentWithSectionHighlight(filePath, sourceSection);
                } else {
                    // セクション情報がない場合は通常表示
                    this.loadFileContent(filePath);
                }
            });
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

    sendTodoToSearch(todoId) {
        const todo = this.todos.find(t => t.id === todoId);
        if (todo) {
            // TODOの内容を検索窓に直接設定
            this.queryInput.value = todo.content;
            this.queryInput.focus();

            // 視覚的フィードバック（一時的にボタンの色を変更）
            const button = event.target;
            const originalText = button.textContent;
            const originalClass = button.className;

            button.textContent = '送信済み';
            button.classList.add('sent');

            setTimeout(() => {
                button.textContent = originalText;
                button.className = originalClass;
            }, 1500);
        }
    }

    openFileInDocumentViewer(filePath, event) {
        console.log('openFileInDocumentViewer 呼び出し:', filePath);
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

    // js-fileexplorer初期化
    initializeFileExplorer() {
        console.log('FileExplorer初期化開始');
        console.log('fileExplorerElement:', this.fileExplorerElement);
        console.log('window.FileExplorer:', window.FileExplorer);

        if (!this.fileExplorerElement) {
            console.error('FileExplorer要素が見つかりません');
            return;
        }

        if (!window.FileExplorer) {
            console.error('FileExplorerクラスが見つかりません。ライブラリが正しく読み込まれていません。');
            this.fileExplorerElement.innerHTML = '<div class="error">ライブラリの読み込みに失敗しました</div>';
            return;
        }

        // 既存のFileExplorerインスタンスがあれば破棄
        if (this.fileExplorer) {
            console.log('既存のFileExplorerを破棄');
            if (this.fileExplorer.Destroy) {
                this.fileExplorer.Destroy();
            }
            this.fileExplorer = null;
        }

        // FileExplorer要素をクリア
        this.fileExplorerElement.innerHTML = '';

        const options = {
            initpath: [
                ['', 'ドキュメント', { canmodify: true }]
            ],
            onrefresh: (folder, required) => {
                console.log('onrefresh呼び出し:', folder, required);
                this.refreshFileExplorer(folder, required);
            },
            onopenfile: (folder, entry) => {
                console.log('onopenfile呼び出し（ダブルクリック）:', folder, entry);
                this.openFileInViewer(entry);
            }
        };

        try {
            console.log('FileExplorer初期化実行:', this.fileExplorerElement, options);
            // 正しい初期化方法
            this.fileExplorer = new window.FileExplorer(this.fileExplorerElement, options);
            console.log('FileExplorer初期化成功:', this.fileExplorer);
        } catch (error) {
            console.error('FileExplorer初期化エラー:', error);
            this.fileExplorerElement.innerHTML = '<div class="error">ファイルエクスプローラーの初期化に失敗しました: ' + error.message + '</div>';
        }
    }

    // ファイルエクスプローラーのリフレッシュ処理
    async refreshFileExplorer(folder, required) {
        try {
            const pathIds = folder.GetPathIDs();
            console.log('リフレッシュ要求:', pathIds);

            // パスを構築（最初の空文字を除去し、残りを結合）
            const folderPath = pathIds.length > 1 ? pathIds.slice(1).join('/') : '';
            const apiUrl = folderPath ? `${this.baseUrl}/api/browse/${folderPath}` : `${this.baseUrl}/api/browse`;

            const response = await fetch(apiUrl);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.allFiles = data.files;

            // ファイル構造をjs-fileexplorer形式に変換
            const entries = this.convertFilesToExplorerFormat(data.files);
            console.log('変換されたエントリ:', entries);

            // フォルダを更新
            folder.SetEntries(entries);

        } catch (error) {
            console.error('ファイル一覧の読み込みに失敗:', error);
            folder.SetEntries([]); // エラー時は空にする
        }
    }

    // ファイル形式をjs-fileexplorer用に変換
    convertFilesToExplorerFormat(files) {
        const entries = [];

        files.forEach(file => {
            const pathParts = file.path.split('/').filter(part => part.length > 0);
            const fileName = pathParts[pathParts.length - 1] || file.path || 'Unknown';
            const isFolder = file.type === 'folder';

            // js-fileexplorer形式のエントリ（オブジェクト形式）
            entries.push({
                id: file.path || '',
                name: fileName,
                type: isFolder ? 'folder' : 'file',
                size: file.size || 0,
                modified: file.modified || new Date().toISOString(),
                canmodify: true,
                candelete: true,
                candownload: !isFolder,
                ext: isFolder ? '' : (fileName.split('.').pop() || ''),
                hash: file.path || '' // ハッシュとしてパスを使用
            });
        });

        return entries;
    }

    // ファイルを開く処理
    openFileInViewer(entry) {
        console.log('ファイルを開く:', entry);

        // js-fileexplorerのentryオブジェクトからパスと情報を取得
        let filePath;
        let fileInfo;

        if (typeof entry === 'string') {
            filePath = entry;
        } else if (entry && entry.id !== undefined) {
            // 直接entryオブジェクトからプロパティを取得
            filePath = entry.id;
            fileInfo = entry;
        } else {
            console.error('ファイルパスを取得できません:', entry);
            return;
        }

        // フォルダの場合は何もしない（FileExplorerが自動的にナビゲーションを処理）
        if (fileInfo && fileInfo.type === 'folder') {
            console.log('フォルダがクリックされました:', filePath);
            return;
        }

        // ファイルの場合のみビューアーで開く
        console.log('ファイルを開きます:', filePath);
        this.loadFileContent(filePath);
    }

    // 新規ファイル作成ボタンの設定
    setupNewFileButton() {
        const newFileBtn = document.getElementById('newFileBtn');
        if (newFileBtn) {
            // 既存のイベントリスナーを削除してから新しいものを追加
            newFileBtn.removeEventListener('click', this.handleNewFileClick);
            this.handleNewFileClick = () => {
                this.showNewFileDialog();
            };
            newFileBtn.addEventListener('click', this.handleNewFileClick);
        }
    }

    // 新規ファイル作成ダイアログを表示
    showNewFileDialog() {
        const filename = prompt('新しいマークダウンファイル名を入力してください（拡張子不要）:');
        if (filename && filename.trim()) {
            this.createNewFile(filename.trim());
        }
    }

    // 新規ファイルを作成
    async createNewFile(filename) {
        try {
            // 現在のフォルダパスを取得
            const currentPath = this.getCurrentFolderPath();

            const response = await fetch(`${this.baseUrl}/api/files/create`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    filename: filename,
                    folder_path: currentPath,
                    content: `# ${filename}\n\n新しいマークダウンファイルです。\n\n`
                })
            });

            const data = await response.json();

            if (response.ok) {
                // ファイルエクスプローラーを更新
                this.refreshCurrentFolder();
                // 作成したファイルを開く
                this.loadFileContent(data.path);
                console.log(`ファイル "${data.filename}" が作成されました`);
            } else {
                alert(`エラー: ${data.error}`);
            }
        } catch (error) {
            console.error('ファイル作成エラー:', error);
            alert('ファイル作成中にエラーが発生しました');
        }
    }

    // 現在のフォルダパスを取得
    getCurrentFolderPath() {
        if (this.fileExplorer && this.fileExplorer.GetCurrentFolder) {
            const folder = this.fileExplorer.GetCurrentFolder();
            if (folder && folder.GetPathIDs) {
                const pathIds = folder.GetPathIDs();
                // 最初の空文字を除去し、残りを結合
                return pathIds.length > 1 ? pathIds.slice(1).join('/') : '';
            }
        }
        return '';
    }

    // 現在のフォルダを再読み込み
    refreshCurrentFolder() {
        if (this.fileExplorer && this.fileExplorer.GetCurrentFolder) {
            const folder = this.fileExplorer.GetCurrentFolder();
            if (folder && folder.Refresh) {
                folder.Refresh();
            }
        }
    }



    async loadFileContent(filePath) {
        console.log('loadFileContent 呼び出し:', filePath);
        if (!filePath) {
            console.log('ファイルパスが空です');
            return;
        }

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
        } catch (error) {
            console.error('ファイル読み込みエラー:', error);
            alert(`ファイル読み込みエラー: ${error.message}`);
        }
    }

    async loadFileContentWithSectionHighlight(filePath, sectionText) {
        if (!filePath) return;

        try {
            const response = await fetch(`${this.baseUrl}/api/files/${encodeURIComponent(filePath)}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.currentDocumentPath = filePath;
            this.documentTitle.textContent = `${this.getFileNameFromPath(filePath)} (${sectionText} をハイライト)`;

            // セクションテキストをハイライトしてMarkdownを変換
            const highlightedContent = this.highlightSectionInMarkdown(data.content, sectionText);
            const htmlContent = this.convertMarkdownToHtml(highlightedContent);
            this.documentContent.innerHTML = htmlContent;

            this.documentViewer.style.display = 'block';

            // デフォルトメッセージを非表示
            const defaultContent = document.getElementById('defaultViewerContent');
            if (defaultContent) {
                defaultContent.style.display = 'none';
            }

            // ハイライト箇所にスクロール
            setTimeout(() => {
                const highlightedElement = this.documentContent.querySelector('.section-highlight');
                if (highlightedElement) {
                    highlightedElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // より目立つようにフォーカスを当てる
                    highlightedElement.focus();
                }
            }, 300);

        } catch (error) {
            console.error('ファイル読み込みエラー:', error);
            this.documentTitle.textContent = 'エラー';
            this.documentContent.innerHTML = `<p>ファイルの読み込みに失敗しました: ${error.message}</p>`;
            this.documentViewer.style.display = 'block';

            // デフォルトメッセージを非表示
            const defaultContent = document.getElementById('defaultViewerContent');
            if (defaultContent) {
                defaultContent.style.display = 'none';
            }
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

            // ハイライト箇所にスクロール
            setTimeout(() => {
                const highlightedElement = this.documentContent.querySelector('.chunk-highlight');
                if (highlightedElement) {
                    highlightedElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // より目立つようにフォーカスを当てる
                    highlightedElement.focus();
                }
            }, 300);

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
        // 空白の違いを許容する正規表現を作成
        const flexiblePattern = this.escapeRegExp(targetText).replace(/\\\s+/g, '\\s+');
        const regex = new RegExp(`(${flexiblePattern})`, 'i');

        const match = fullContent.match(regex);
        if (match) {
            const beforeText = fullContent.substring(0, match.index);
            const matchedText = match[0];
            const afterText = fullContent.substring(match.index + matchedText.length);

            return beforeText + `<span class="chunk-highlight">${matchedText}</span>` + afterText;
        }

        // より柔軟なマッチングを試す（複数の単語に分けて検索）
        const words = targetText.trim().split(/\s+/).filter(word => word.length > 2);
        if (words.length > 1) {
            // 最初の数単語でマッチを試す
            const partialText = words.slice(0, Math.min(3, words.length)).join(' ');
            const partialPattern = this.escapeRegExp(partialText).replace(/\\\s+/g, '\\s+');
            const partialRegex = new RegExp(`(${partialPattern})`, 'i');

            const partialMatch = fullContent.match(partialRegex);
            if (partialMatch) {
                const beforeText = fullContent.substring(0, partialMatch.index);
                const matchedText = partialMatch[0];
                const afterText = fullContent.substring(partialMatch.index + matchedText.length);

                return beforeText + `<span class="chunk-highlight">${matchedText}</span>` + afterText;
            }
        }

        return fullContent;
    }

    highlightSectionInMarkdown(fullContent, sectionText) {
        console.log('highlightSectionInMarkdown 呼び出し');
        console.log('検索対象セクション:', sectionText);

        // セクションテキストをクリーンアップ
        const cleanSectionText = sectionText.trim();

        // マークダウンヘッダー形式のパターンを試す（より柔軟な検索）
        const headerPatterns = [
            new RegExp(`^(#{1,6})\\s*${this.escapeRegExp(cleanSectionText)}\\s*$`, 'im'),  // # Title形式
            new RegExp(`^(#{1,6})\\s*${this.escapeRegExp(cleanSectionText)}`, 'im'),       // # Titleで始まる行
            new RegExp(this.escapeRegExp(cleanSectionText), 'i')                          // 直接テキストマッチ
        ];

        for (const pattern of headerPatterns) {
            const match = fullContent.match(pattern);
            console.log(`パターン "${pattern}" のマッチ結果:`, match ? match[0] : 'なし');

            if (match) {
                const beforeText = fullContent.substring(0, match.index);
                const matchedText = match[0];
                const afterText = fullContent.substring(match.index + matchedText.length);

                return beforeText + `<span class="section-highlight">${matchedText}</span>` + afterText;
            }
        }

        // 部分的なキーワードマッチを試す
        const keywords = cleanSectionText.split(' ').filter(word => word.length > 2);
        if (keywords.length > 0) {
            const keywordPattern = new RegExp(`(${keywords.map(this.escapeRegExp).join('|')})`, 'gi');
            const keywordMatch = fullContent.match(keywordPattern);
            console.log(`キーワードマッチ結果:`, keywordMatch);

            if (keywordMatch) {
                // 最初のキーワードをハイライト
                return fullContent.replace(keywordPattern, '<span class="section-highlight">$1</span>');
            }
        }

        // マッチしない場合はそのまま返す
        console.log('マッチするセクションが見つかりませんでした');
        return fullContent;
    }

    escapeRegExp(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    insertSectionHighlightInOriginalText(fullContent, targetText) {
        console.log('insertSectionHighlightInOriginalText 呼び出し');
        console.log('対象テキスト:', targetText);

        // 空白の違いを許容する正規表現を作成
        const flexiblePattern = this.escapeRegExp(targetText).replace(/\\\s+/g, '\\s+');
        const regex = new RegExp(`(${flexiblePattern})`, 'i');

        console.log('正規表現パターン:', flexiblePattern);

        const match = fullContent.match(regex);
        console.log('マッチ結果:', match ? match[0] : 'マッチなし');

        if (match) {
            const beforeText = fullContent.substring(0, match.index);
            const matchedText = match[0];
            const afterText = fullContent.substring(match.index + matchedText.length);

            return beforeText + `<span class="section-highlight">${matchedText}</span>` + afterText;
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



    closeDocumentViewer() {
        this.documentViewer.style.display = 'none';
        this.currentDocumentPath = null;

        // デフォルトメッセージを再表示
        const defaultContent = document.getElementById('defaultViewerContent');
        if (defaultContent) {
            defaultContent.style.display = 'block';
        }


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

            // ファイルエクスプローラーを更新
            this.refreshCurrentFolder();

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
            this.refreshCurrentFolder();

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
            this.refreshCurrentFolder(); // 元に戻す
        } catch (error) {
            console.error('名前変更エラー:', error);
            alert(`名前変更エラー: ${error.message}`);
            this.refreshCurrentFolder(); // 元に戻す
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



}

// 1回だけ初期化されるように管理
let ragInterfaceInitialized = false;

function initializeRAGInterface() {
    if (ragInterfaceInitialized) {
        console.log('RAGInterface は既に初期化済みです');
        return;
    }

    console.log('RAGInterface を初期化します');
    const ragInterface = new RAGInterface();
    ragInterface.initialize();
    window.ragInterface = ragInterface;
    ragInterfaceInitialized = true;
}

// すべてのリソース（画像、CSS、JSファイル）が読み込まれた後に初期化
window.addEventListener('load', () => {
    console.log('window.load イベント発火');
    console.log('FileExplorer利用可能:', !!window.FileExplorer);
    initializeRAGInterface();
});

// DOMContentLoadedでも試す（window.loadより早く発火する場合がある）
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOMContentLoaded イベント発火');
    console.log('FileExplorer利用可能:', !!window.FileExplorer);

    if (window.FileExplorer) {
        initializeRAGInterface();
    }
});