-- queries.sql
-- SQL-запросы для базы данных «Конвертер изображений в ASCII-арт»
-- База данных: ascii_art.db (SQLite)

-- ===========================================================================
-- Запрос 1. Все конвертации для конкретного изображения
-- Показывает историю обработки одного файла с разными настройками.
-- ===========================================================================
SELECT c.id,
       c.ascii_width,
       c.ascii_height,
       c.charset,
       c.inverted,
       c.colored,
       c.converted_at
FROM   conversions c
WHERE  c.image_id = 1          -- подставить нужный id изображения
ORDER  BY c.converted_at DESC;


-- ===========================================================================
-- Запрос 2. История последних N конвертаций с именами файлов
-- Объединяет таблицы images и conversions для отображения истории.
-- ===========================================================================
SELECT i.filename,
       c.ascii_width,
       c.ascii_height,
       c.charset,
       c.inverted,
       c.colored,
       c.converted_at
FROM   conversions c
JOIN   images i ON c.image_id = i.id
ORDER  BY c.converted_at DESC
LIMIT  20;


-- ===========================================================================
-- Запрос 3. Статистика конвертаций по наборам символов
-- Позволяет оценить, какой charset используется чаще всего.
-- ===========================================================================
SELECT charset,
       COUNT(*) AS total
FROM   conversions
GROUP  BY charset
ORDER  BY total DESC;


-- ===========================================================================
-- Запрос 4. Все экспорты с деталями конвертации и исходного файла
-- Трёхтабличное соединение: exports + conversions + images.
-- ===========================================================================
SELECT e.id            AS export_id,
       i.filename      AS source_file,
       c.charset,
       c.ascii_width,
       e.export_path,
       e.export_format,
       e.exported_at
FROM   exports e
JOIN   conversions c ON e.conversion_id = c.id
JOIN   images      i ON c.image_id      = i.id
ORDER  BY e.exported_at DESC;


-- ===========================================================================
-- Запрос 5. Топ изображений по количеству конвертаций
-- LEFT JOIN учитывает изображения, которые ни разу не конвертировались.
-- ===========================================================================
SELECT i.filename,
       COUNT(c.id) AS conv_count
FROM   images i
LEFT JOIN conversions c ON i.id = c.image_id
GROUP  BY i.id
ORDER  BY conv_count DESC
LIMIT  5;
