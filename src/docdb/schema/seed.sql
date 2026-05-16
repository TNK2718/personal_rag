-- DocDB built-in type seeds (idempotent).
-- Inserted after schema.sql so that a fresh database has the familiar
-- person / org / place / task / project / event entity types and the
-- assigned_to / mentions / belongs_to / part_of / reports_to / located_in /
-- depends_on / member_of / participated_in relation types available out of
-- the box.
--
-- These rows are INSERT OR IGNORE: if a user has edited the same slug,
-- the existing row wins. Built-ins are marked with is_builtin = 1 so the
-- Settings UI can render them differently (e.g., prevent deletion).

INSERT OR IGNORE INTO entity_types (slug, label, description, fields_schema, extraction_hint, is_builtin)
VALUES
    ('person', '人物', '実在 / 言及された個人。組織名や役職と混同しない。',
     '[]',
     '本文中で言及された人名のみ。役職や敬称は canonical_name に含めない。',
     1),
    ('org', '組織', '会社・チーム・学校・部署など。',
     '[]',
     '組織・チーム・部署。略称は aliases に。',
     1),
    ('place', '場所', '地名・施設名・部屋など。',
     '[]',
     '地名・建物名・会議室など物理的な場所。',
     1),
    ('task',
     'タスク',
     '本文に書かれた未完了の作業項目。',
     '[
        {"name":"status","label":"Status","type":"enum","required":true,"default":"pending",
         "options":["pending","in_progress","completed","cancelled"]},
        {"name":"priority","label":"Priority","type":"enum","required":true,"default":"medium",
         "options":["high","medium","low"]},
        {"name":"due_date","label":"Due","type":"date","required":false}
      ]',
     '未完了の作業項目のみ抽出。完了済み (例: [x]) は除外。canonical_name はタスク本文そのもの。緊急/asap/急 → priority=high、後で/将来 → low、それ以外は medium。',
     1),
    ('project',
     'プロジェクト',
     '継続的な施策・プロダクト・取り組み。組織 (org) や単発タスク (task) とは区別する。',
     '[
        {"name":"status","label":"Status","type":"enum","required":true,"default":"active",
         "options":["active","paused","completed","archived"]},
        {"name":"start_date","label":"Start","type":"date","required":false},
        {"name":"end_date","label":"End","type":"date","required":false}
      ]',
     'プロジェクト名・プロダクト名・施策名。会社名や部署名 (org) と混同しない。',
     1),
    ('event',
     'イベント',
     '会議・打ち合わせ・発表会など時点を持つ出来事。',
     '[
        {"name":"start_at","label":"Start","type":"datetime","required":false},
        {"name":"end_at","label":"End","type":"datetime","required":false}
      ]',
     '会議・打ち合わせ・発表会・キックオフなど。canonical_name はイベント名 (例: "2026年度キックオフ")。',
     1);

INSERT OR IGNORE INTO relation_types
    (slug, label, description, inverse_label,
     source_type_slug, target_type_slug, fields_schema, extraction_hint, is_builtin)
VALUES
    ('assigned_to', '担当', 'タスクや責務を人物 / 組織に紐付ける。',
     'has_assignment',
     NULL, NULL,
     '[]',
     'タスク entity から人物 / 組織 entity へ。',
     1),
    ('mentions', '言及', '広い意味で関連あり (デフォルトの弱い結合)。',
     'mentioned_by',
     NULL, NULL,
     '[]',
     '具体的な意味関係が分からない場合の汎用エッジ。',
     1),
    ('belongs_to', '所属', '人物が所属する組織を表す。',
     'has_member',
     'person', 'org',
     '[]',
     '人物 (source) がどの組織 (target) に所属するか。役職や肩書ではなく所属先のみ。',
     1),
    ('part_of', '一部', 'ある組織がより大きい組織の一部であることを表す。',
     'has_part',
     'org', 'org',
     '[]',
     '部署・子会社・チーム (source) が、より大きい組織 (target) の一部である関係。',
     1),
    ('reports_to', '上司', 'レポートライン。部下が上司に報告する関係。',
     'has_report',
     'person', 'person',
     '[]',
     '部下 (source) が上司 (target) に報告する関係。同僚関係には使わない。',
     1),
    ('located_in', '所在地', '任意の entity が物理的に存在する場所。',
     'location_of',
     NULL, 'place',
     '[]',
     'org の本社・person の居住地・event の会場など。target は必ず place。',
     1),
    ('depends_on', '依存', 'タスク間の依存関係。',
     'blocks',
     'task', 'task',
     '[]',
     'source タスクが完了するには target タスクの完了が必要、という依存関係。',
     1),
    ('member_of', 'メンバー', 'プロジェクトへの参加。所属組織 (belongs_to) とは別。',
     'has_member',
     'person', 'project',
     '[]',
     '人物 (source) がプロジェクト (target) に参加していること。',
     1),
    ('participated_in', '参加', '会議・イベントへの参加・出席。',
     'participants',
     'person', 'event',
     '[]',
     '人物 (source) が会議・イベント (target) に参加・出席した事実。',
     1);
