# genkai-surface 示例任务文件

这些任务文件只使用仓库里已有的结构，下载代码后可以直接运行。使用方法见
[表面建模使用手册](../../docs/surface-modeling-user-guide.md)。

| 文件 | 方法 | 内容 |
| --- | --- | --- |
| `01_slab_sno2.yaml` | slab | SnO2 块体切出 (110) 面 |
| `02_vacancy_ceo2.yaml` | vacancy | CeO2(111) 上 1 个、2 个 O 空位，各 3 个构型 |
| `03_adsorbate_h2o_ceo2.yaml` | adsorbate | CeO2(111) 的 Ce 位点上放 1 个、2 个 H2O |
| `04_cluster_pt13_ceo2.yaml` | cluster | Pt13（fcc）放在 CeO2(111) 上 |
| `05_sam_sno2_butanoic.yaml` | sam | 丁酸单齿锚定在 SnO2 最稳定晶面上，每个晶胞 1 个、2 个分子 |
| `06_ald_full_and_partial.yaml` | ald | 一个文件两个任务：a-TiO2 全覆盖膜；a-SnO2 岛部分覆盖 SnO2(101) |
| `07_amorphous_slab_tio2.yaml` | amorphous_slab | a-TiO2 切出 10 Å 纯非晶表面，2 个不同切割位置 |
| `08_chain_amorphous_then_sam.yaml` | amorphous_slab → sam | 串联：先切非晶 SnO2 表面，再在上面放丁酸 SAM |

```bash
genkai-surface check examples/surface_jobs/05_sam_sno2_butanoic.yaml   # 只检查
genkai-surface run examples/surface_jobs/05_sam_sno2_butanoic.yaml     # 运行
```

运行结果写在本目录的 `runs/` 下（已加入 `.gitignore`），可以随时删除。
所有示例只生成未弛豫的结构，不计算能量。
