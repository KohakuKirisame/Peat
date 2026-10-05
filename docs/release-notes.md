Peat 0.3.1 fixes international charts and adds market-curve inspection.

- Resolve international Trading 212 symbols, including the Airbus legacy ID `AIRp_EQ → AIR.PA`, with instrument/exchange metadata fallback and preserved user overrides.
- Clear the previous holding's chart and company details when switching instruments or chart queries.
- Inspect Treasury, energy and precious-metal curves with mouse hover, keyboard or touch. Each point shows its actual date/time, value and unit; commodity timestamps include the exchange timezone.
- Preserve timestamp/value alignment across missing observations and avoid duplicate labels on short candle histories.

Peat 0.3.1 修复非美股 K 线，并增加市场曲线数值查看。

- 修复 Trading212 非美股代码转换，包含 Airbus 的 `AIRp_EQ → AIR.PA`；增加标的/交易所元数据回退，保留手动映射优先级。
- 切换标的或行情请求时，清除上一持仓的 K 线与公司信息。
- 美债、能源与贵金属曲线支持鼠标悬浮、键盘和触屏查看日期/时间、具体数值及单位；商品时间包含交易所时区。
- 缺失行情不会造成时间与数值错位，少量 K 线不再重复显示日期标签。

Keep the existing data volume when upgrading. No new API registration is needed. Existing manually saved chart symbols remain in effect and can be edited in the chart.

升级时保留现有数据卷，无需注册新的 API。原有手动保存的行情代码继续生效，可在图表中修改。

Image: `ghcr.io/kohakukirisame/peat:0.3.1` (`linux/amd64`, `linux/arm64`).

```sh
docker compose pull
docker compose up -d
```
