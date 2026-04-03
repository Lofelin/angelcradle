# 任务：子宫实现

- [ ] 1. 项目基础
  - [ ] 1.1 创建 `pyproject.toml`
  - [ ] 1.2 创建 `.gitignore`
  - [ ] 1.3 创建 `womb/` 包目录和 `__init__.py`

- [ ] 2. 数据模型
  - [ ] 2.1 创建 `womb/seed.py`：FamilyMember、Seed dataclass + parse_seed() 函数
  - [ ] 2.2 创建 `womb/baby.py`：Baby dataclass + 编号生成逻辑 + to_dict()

- [ ] 3. 遗传表达
  - [ ] 3.1 创建 `womb/genetics.py`：express() 函数 + CONCEPTION_PROMPT

- [ ] 4. 入口
  - [ ] 4.1 在 `womb/__init__.py` 中实现 conceive() 函数，串联 seed → genetics → baby

- [ ] 5. 种子
  - [ ] 5.1 创建 `seeds/korin.yaml` 示例种子文件

- [ ] 6. 验证
  - [ ] 6.1 手动验证：用 korin.yaml 孕育一个婴儿，检查输出数据
