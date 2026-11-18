-- 一版架构的一条人员任职；附带人员姓名、类型及自身岗位名称。
-- 上下级关系统一由岗位树表达。
-- 原始人员与任职来源仍各自独立；消费层用一张任职表回答“谁在哪个岗”。
-- 姓名和类型来自当前人员主档，不据此推断历史姓名或历史人员类型。
select a.assignment_id, a.snapshot_code, a.employee_code, e.employee_name, e.role_kind,
    a.position_code, p.position_name
from {{ ref('stg_employee_positions') }} a
join {{ ref('stg_positions') }} p using (snapshot_code, position_code)
join {{ ref('stg_people') }} e using (employee_code)
