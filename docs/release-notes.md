Peat 0.4.0 adds holding horizons and interface zoom.

- Choose ultra short term (intraday–3 trading days), short term (1–4 weeks), or medium/long term (1 month or longer), independently of the five risk styles.
- Both LLM providers receive the selected horizon prompt. Each horizon template can be edited and restored; proposed actions include holding duration, review points and exit conditions.
- Background tasks and archived briefs preserve the selected horizon and exact prompt. Earlier reports retain their original metadata.
- Set interface zoom from 80% to 200% in the top bar or Settings → Appearance, with a 100% reset. Preferences are saved per account in the current browser, and layouts adapt to the zoom level.
- Includes v0.3.1's international candlestick fixes and dated hover/touch tooltips for Treasury, energy and precious-metal curves.

Peat 0.4.0 新增持有周期与界面缩放。

- 独立选择超短线（当日–3 个交易日）、短线（1–4 周）或中长线（1 个月以上），可与五档投资风格组合使用。
- 两种 LLM 均接入对应周期提示词。三套模板可单独编辑和恢复，操作建议包含计划持有时间、复核点和退出条件。
- 后台任务与历史简报保存所选周期及实际提示词，旧报告保留原有元信息。
- 顶部栏和“设置 → 外观”支持 80%–200% 界面缩放，可恢复 100%；按账户保存在当前浏览器，页面随缩放调整布局。
- 包含 v0.3.1 的非美股 K 线修复，以及美债、能源和贵金属曲线的日期/数值悬浮与触屏提示。

Keep the existing data volume when upgrading. Existing accounts default to medium/long term; saved custom base and style prompts are preserved. Generate a new brief to apply a holding horizon. No new API registration is needed.

升级时保留现有数据卷，已有账户默认使用中长线，原有通用及策略自定义提示词继续保留。重新生成简报即可应用持有周期，无需注册新 API。

Image: `ghcr.io/kohakukirisame/peat:0.4.0` (`linux/amd64`, `linux/arm64`).

```sh
docker compose pull
docker compose up -d
```
