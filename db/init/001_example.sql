-- 全部是合成数据。raw 模拟已抽取的业务源数据；app 保存应用登录与实时授权。
-- dbt 只消费 raw，按 staging → intermediate → marts 构建事实、维度与桥表。
-- 只在空数据库初始化时执行，临时数据库重建后可复现同一组场景。
CREATE SCHEMA raw;
CREATE SCHEMA app;
-- 业务人员主档：工号、姓名和业务人员类型独立于应用账号。
CREATE TABLE raw.employees (
  employee_code text PRIMARY KEY, employee_name text NOT NULL,
  role_kind text NOT NULL DEFAULT 'representative'
);
-- 应用登录账号：绑定工号，只保存当前账号状态。
-- 业务人员可以没有登录账号，人员目录与历史业绩仍由业务归属决定。
CREATE TABLE app.users (
  employee_code text PRIMARY KEY, active boolean NOT NULL
);
-- 本例自定义的当前授权。若已有 IAM 或按当前任职授权，可替换这份数据来源。
-- 岗位授权适用于该岗位的全部已生效架构版本；历史查询统一使用同一份授权。
CREATE TABLE app.access_grants (
  employee_code text NOT NULL REFERENCES app.users,
  root_position_code text NOT NULL,
  PRIMARY KEY (employee_code, root_position_code)
);
-- 这就是架构表：position_code 是节点，parent_code 是上级，snapshot_code 区分历史版本。
-- dbt 按配置的业务日期选择已生效版本，不需要额外的组织发布表。
CREATE TABLE raw.positions (
  snapshot_code text NOT NULL, position_code text NOT NULL, position_name text NOT NULL,
  parent_code text, PRIMARY KEY (snapshot_code, position_code)
);
-- 这三张关系表分别回答：谁在哪个辖区、辖区有哪些医院、辖区有哪些产品。
-- id 是记录主键；唯一约束确保同一快照下的相同业务关系只保存一条。
CREATE TABLE raw.employee_positions (
  id integer PRIMARY KEY, snapshot_code text NOT NULL, employee_code text NOT NULL, position_code text NOT NULL,
  CONSTRAINT employee_positions_business_key UNIQUE (snapshot_code, employee_code, position_code)
);
CREATE TABLE raw.position_account_histories (
  id integer PRIMARY KEY, snapshot_code text NOT NULL, position_code text NOT NULL,
  account_code text NOT NULL, account_type text NOT NULL,
  CONSTRAINT position_accounts_business_key UNIQUE (snapshot_code, position_code, account_code, account_type)
);
CREATE TABLE raw.position_product_histories (
  id integer PRIMARY KEY, snapshot_code text NOT NULL, position_code text NOT NULL, product_code text NOT NULL,
  CONSTRAINT position_products_business_key UNIQUE (snapshot_code, position_code, product_code)
);
-- 医院和产品维度都是唯一键，不把多对多组织覆盖预先拼进宽表。
CREATE TABLE raw.hospitals (hospital_code text PRIMARY KEY, hospital_name text NOT NULL, province_name text NOT NULL);
CREATE TABLE raw.products (product_code text PRIMARY KEY, product_name text NOT NULL);
-- 交易粒度销售事实：一个 sales_id 一份金额，不按能查看它的人复制。
CREATE TABLE raw.sales (
  sales_id text PRIMARY KEY, sales_date date NOT NULL,
  hospital_code text NOT NULL REFERENCES raw.hospitals,
  product_code text NOT NULL REFERENCES raw.products,
  sales_amount numeric(18,2) NOT NULL, sales_quantity numeric(18,2) NOT NULL
);

-- 先建立当前十一月和旧十月组织，再补充一、二月的历史场景。
INSERT INTO raw.employees (employee_code, employee_name, role_kind) VALUES
  ('E001', '张三', 'representative'), ('E002', '李四', 'representative'),
  ('M001', '王经理', 'manager'), ('E003', '陈代表', 'representative'),
  ('E004', '无辖区账号', 'representative'), ('E005', '已停用账号', 'representative'),
  ('E006', '张三', 'representative'), ('E007', '赵离职', 'representative'),
  ('M002', '新获授权审计员', 'auditor'), ('M003', '已调岗经理', 'manager');
-- 演示账号单独装载；账号表不再承担人员主档职责。
INSERT INTO app.users (employee_code, active) VALUES
  ('E001', true), ('E002', true), ('M001', true),
  ('E003', true), ('E004', true), ('E005', false),
  ('E006', true), ('E007', false), ('M002', true), ('M003', true);
-- 审计员可获显式岗位授权；调岗经理只获T9，各版本查询都受这份授权限制。
INSERT INTO app.access_grants (employee_code, root_position_code) VALUES
  ('M001', 'M'), ('M001', 'OLD'),
  ('M002', 'M'), ('M003', 'T9'),
  ('E001', 'T1'), ('E002', 'T2'),
  ('E003', 'T1'), ('E003', 'T2'), ('E006', 'T2');
INSERT INTO raw.positions VALUES
  ('2026-10','OLD','旧辖区',NULL),
  ('2026-11','M','经理辖区',NULL),
  ('2026-11','T1','辖区一','M'), ('2026-11','T2','辖区二','M'),
  ('2026-11','T9','其他经理的辖区',NULL);
-- E003 兼任 T1/T2；一人多辖区属于正常关系，不应造成共享销售额重复。
INSERT INTO raw.employee_positions VALUES
  (1,'2026-10','E001','OLD'), (2,'2026-10','M001','OLD'),
  (3,'2026-11','E001','T1'), (4,'2026-11','E002','T2'),
  (5,'2026-11','M001','M'), (6,'2026-11','E003','T1'),
  (7,'2026-11','E003','T2'),
  (9,'2026-11','E006','T2');
-- 此销售示例只支持医院覆盖，医生关系不混入基础数据；T1、T2 共享 H1 是正常关系。
INSERT INTO raw.position_account_histories VALUES
  (1,'2026-10','OLD','H9','hospital'),
  (2,'2026-11','T1','H1','hospital'), (3,'2026-11','T1','H2','hospital'),
  (5,'2026-11','T2','H1','hospital'), (6,'2026-11','T2','H3','hospital'),
  (7,'2026-11','T9','H4','hospital');
-- 同辖区内组合医院与产品。T1 只有 P1，因此 H2/P2 不属于 T1 或 M 团队。
INSERT INTO raw.position_product_histories VALUES
  (1,'2026-10','OLD','P9'),
  (2,'2026-11','T1','P1'),
  (4,'2026-11','T2','P1'), (5,'2026-11','T2','P2'),
  (6,'2026-11','T9','P1'), (7,'2026-11','T9','P3');
INSERT INTO raw.hospitals VALUES
  ('H1','示例中心医院','北京市'), ('H2','示例第一医院','河北省'),
  ('H3','示例第二医院','山东省'), ('H4','示例第三医院','上海市'),
  ('H9','示例第四医院','江苏省');
INSERT INTO raw.products VALUES
  ('P1','产品一'), ('P2','产品二'), ('P3','产品三'), ('P9','旧产品');
-- 一月有效事实：H1/P1=60+40=100，H2/P1=15+15=30，H3/P2=25+25=50。
-- 相同金额的不同交易需要保留；不能 SUM(DISTINCT sales_amount)。
-- 800、700、999、600 是不同越权/历史场景的对照数，不应混进经理当前范围 180。
INSERT INTO raw.sales VALUES
  ('J01','2026-01-03','H1','P1',60,6), ('J02','2026-01-20','H1','P1',40,4),
  ('J03','2026-01-04','H2','P1',15,1), ('J04','2026-01-21','H2','P1',15,2),
  ('J05','2026-01-05','H3','P2',25,2), ('J06','2026-01-22','H3','P2',25,3),
  ('J07','2026-01-06','H2','P2',800,80),
  ('J08','2026-01-07','H4','P3',700,70), ('J09','2026-01-08','H9','P9',999,99),
  ('J10','2026-01-09','H4','P1',600,60),
  ('F01','2026-02-03','H1','P1',120,12),
  ('F02','2026-02-04','H2','P1',40,4), ('F03','2026-02-05','H3','P2',60,6);
-- 从当前覆盖关系派生两份合成历史快照；二月张三从 T1 转到 T2。
INSERT INTO raw.positions
  SELECT periods.snapshot_code, positions.position_code, positions.position_name, positions.parent_code
  FROM raw.positions positions CROSS JOIN (VALUES ('2026-01'), ('2026-02')) periods(snapshot_code)
  WHERE positions.snapshot_code = '2026-11';
INSERT INTO raw.employee_positions
  SELECT assignments.id + periods.id_offset, periods.snapshot_code, assignments.employee_code,
    CASE WHEN periods.snapshot_code = '2026-02' AND assignments.employee_code = 'E001'
      THEN 'T2' ELSE assignments.position_code END
  FROM raw.employee_positions assignments
  CROSS JOIN (VALUES ('2026-01', 100), ('2026-02', 200)) periods(snapshot_code, id_offset)
  WHERE assignments.snapshot_code = '2026-11';
INSERT INTO raw.position_account_histories
  SELECT relations.id + periods.id_offset, periods.snapshot_code,
    relations.position_code, relations.account_code, relations.account_type
  FROM raw.position_account_histories relations
  CROSS JOIN (VALUES ('2026-01', 100), ('2026-02', 200)) periods(snapshot_code, id_offset)
  WHERE relations.snapshot_code = '2026-11';
INSERT INTO raw.position_product_histories
  SELECT relations.id + periods.id_offset, periods.snapshot_code, relations.position_code, relations.product_code
  FROM raw.position_product_histories relations
  CROSS JOIN (VALUES ('2026-01', 100), ('2026-02', 200)) periods(snapshot_code, id_offset)
  WHERE relations.snapshot_code = '2026-11';
-- 离职人员可作为历史对象，但不能以已停用身份登录。
INSERT INTO raw.employee_positions VALUES (500, '2026-01', 'E007', 'T1');
-- M003 曾管理 M，今天只获 T9 授权，用于证明“历史归属不等于当前授权”。
INSERT INTO raw.employee_positions VALUES
  (502, '2026-01', 'M003', 'M'), (503, '2026-11', 'M003', 'T9');
-- 在主数据装载完成后建立外键，后续写入不能产生孤立岗位、人员、医院或产品关系。
ALTER TABLE raw.positions ADD CONSTRAINT positions_parent_fk
  FOREIGN KEY (snapshot_code, parent_code) REFERENCES raw.positions (snapshot_code, position_code);
ALTER TABLE raw.employee_positions ADD CONSTRAINT employee_positions_person_fk
  FOREIGN KEY (employee_code) REFERENCES raw.employees (employee_code);
ALTER TABLE raw.employee_positions ADD CONSTRAINT employee_positions_territory_fk
  FOREIGN KEY (snapshot_code, position_code) REFERENCES raw.positions (snapshot_code, position_code);
ALTER TABLE raw.position_account_histories ADD CONSTRAINT position_accounts_territory_fk
  FOREIGN KEY (snapshot_code, position_code) REFERENCES raw.positions (snapshot_code, position_code);
ALTER TABLE raw.position_account_histories ADD CONSTRAINT position_accounts_hospital_fk
  FOREIGN KEY (account_code) REFERENCES raw.hospitals (hospital_code);
ALTER TABLE raw.position_account_histories ADD CONSTRAINT position_accounts_hospital_type CHECK (account_type = 'hospital');
ALTER TABLE raw.position_product_histories ADD CONSTRAINT position_products_territory_fk
  FOREIGN KEY (snapshot_code, position_code) REFERENCES raw.positions (snapshot_code, position_code);
ALTER TABLE raw.position_product_histories ADD CONSTRAINT position_products_product_fk
  FOREIGN KEY (product_code) REFERENCES raw.products (product_code);
-- 为首次 Cube 查询提供统计信息，不修改指标或授权含义。
ANALYZE;
