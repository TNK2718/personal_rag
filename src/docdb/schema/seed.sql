-- DocDB built-in type seeds (idempotent).
-- Inserted after schema.sql so that a fresh database has the familiar
-- person / org / place / task entity types and the assigned_to / mentions
-- relation types available out of the box.
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
     1);

INSERT OR IGNORE INTO relation_types (slug, label, description, inverse_label, fields_schema, extraction_hint, is_builtin)
VALUES
    ('assigned_to', '担当', 'タスクや責務を人物 / 組織に紐付ける。',
     'has_assignment',
     '[]',
     'タスク entity から人物 / 組織 entity へ。',
     1),
    ('mentions', '言及', '広い意味で関連あり (デフォルトの弱い結合)。',
     'mentioned_by',
     '[]',
     '具体的な意味関係が分からない場合の汎用エッジ。',
     1);
