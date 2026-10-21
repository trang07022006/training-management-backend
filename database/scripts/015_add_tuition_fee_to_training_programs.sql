-- 009 may already include this column in databases initialized from the current
-- schema snapshot. Keep this migration safe for both historical layouts.
SET @has_standard_tuition_fee = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'training_programs'
      AND column_name = 'standard_tuition_fee'
);
SET @add_standard_tuition_fee_sql = IF(
    @has_standard_tuition_fee = 0,
    'ALTER TABLE training_programs ADD COLUMN standard_tuition_fee INT UNSIGNED NULL',
    'DO 0'
);
PREPARE add_standard_tuition_fee FROM @add_standard_tuition_fee_sql;
EXECUTE add_standard_tuition_fee;
DEALLOCATE PREPARE add_standard_tuition_fee;
