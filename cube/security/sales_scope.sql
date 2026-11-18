-- 一行是一个可用于事实过滤的 (销售月, 医院, 产品)。本查询不读销售事实。
-- 参数依次为月份→快照 JSON、对象工号数组、登录工号、组合上限加一、组合上限。
WITH periods AS (
    SELECT key AS month, value AS snapshot_code FROM jsonb_each_text(%s::jsonb)
), versions AS (
    SELECT DISTINCT snapshot_code FROM periods
), subjects AS (
    SELECT unnest(%s::text[]) AS employee_code
), grants AS (
    SELECT root_position_code FROM app.access_grants WHERE employee_code = %s
), assignments AS (
    SELECT a.snapshot_code, a.employee_code, a.position_code
    FROM marts.mart_employee_positions a JOIN versions USING (snapshot_code) JOIN subjects USING (employee_code)
), allowed_positions AS (
    SELECT DISTINCT t.snapshot_code, t.descendant_position_code AS position_code
    FROM grants g JOIN marts.mart_position_tree t ON t.ancestor_position_code = g.root_position_code
    JOIN versions USING (snapshot_code)
), directory AS (
    SELECT * FROM allowed_positions
    UNION
    SELECT t.snapshot_code, t.ancestor_position_code FROM grants g
    JOIN marts.mart_position_tree t ON t.descendant_position_code = g.root_position_code
    JOIN versions USING (snapshot_code)
), requested_positions AS (
    SELECT DISTINCT t.snapshot_code, t.descendant_position_code AS position_code
    FROM assignments a JOIN marts.mart_position_tree t
      ON t.snapshot_code = a.snapshot_code AND t.ancestor_position_code = a.position_code
), outside_positions AS (
    SELECT * FROM requested_positions EXCEPT SELECT * FROM allowed_positions
), units AS (
    SELECT DISTINCT p.month, hp.hospital_code, hp.product_code
    FROM requested_positions r JOIN marts.mart_position_hp hp USING (snapshot_code, position_code)
    JOIN periods p USING (snapshot_code)
    LIMIT %s
), decision AS MATERIALIZED (
    SELECT CASE
      WHEN EXISTS (
          SELECT v.snapshot_code, s.employee_code FROM versions v CROSS JOIN subjects s
          EXCEPT SELECT a.snapshot_code, a.employee_code FROM assignments a JOIN directory USING (snapshot_code, position_code)
      ) THEN 'hidden_subject'
      WHEN (SELECT count(*) FROM units) > %s THEN 'too_large'
      WHEN NOT EXISTS (SELECT 1 FROM units) THEN 'empty'
      -- 对象的所有岗位都已获准时，直接复用去重结果。兼岗超出授权岗位才核对覆盖交集。
      WHEN NOT EXISTS (SELECT 1 FROM outside_positions) THEN 'ok'
      WHEN EXISTS (
          SELECT hp.snapshot_code, hp.hospital_code, hp.product_code
          FROM outside_positions o JOIN marts.mart_position_hp hp USING (snapshot_code, position_code)
          EXCEPT
          SELECT hp.snapshot_code, hp.hospital_code, hp.product_code
          FROM allowed_positions a JOIN marts.mart_position_hp hp USING (snapshot_code, position_code)
      ) THEN 'partial'
      ELSE 'ok' END AS status
)
SELECT d.status, u.month, u.hospital_code, u.product_code
FROM decision d LEFT JOIN units u ON d.status = 'ok'
