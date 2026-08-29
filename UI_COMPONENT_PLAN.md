# Internal Linking Engine — UI component plan

Источники: `Docs/session-notes/UI_COMPONENT_VOCABULARY.md`, `UI_INTERFACE_STANDARD.md`,
`ONBOARDING_FIRST_LAUNCH_STANDARD.md`. Реализация строго из `imperal_sdk.ui` — не
мечта, а то, что реально рендерится.

## 0. Разница с идеальной картиной (см. IDEAL_ONBOARDING.md)

- Нет живого push-обновления прогресса сканирования изнутри панели (L9-класс
  ограничение) — прогресс сканирования показывается через ручное обновление
  (`ui.Button("Обновить статус")`) или через `refresh_panels` после завершения
  фоновой задачи, не непрерывный прогресс-бар в реальном времени.
- Нет built-in построчного diff-редактора с чекбоксами на каждую строку — эмулируется
  через `DataTable` (одна строка = один предлагаемый анкор/CTA) + одна кнопка apply
  на весь план целиком (MVP), построчный selective-apply — roadmap-пункт.
- Счётчик "N подтверждений до Full-auto" — реализуем как простое число в `Stat`,
  не отдельный визуальный progress-виджет доверия (в словаре `ui` нет спец-примитива
  под это, `Stat`+`trend` покрывает).

## 1. Компоненты

| Экран | Примитивы | Почему именно эти |
|---|---|---|
| Sidebar (left) | `ui.Stack`(direction="v", align="start") + `ui.Divider` + `ui.ListItem` навигация (Сайты / Прогоны / Настройки) + `ui.Badge`(статус движка по активному сайту) | Без карточек, по стандарту UI_INTERFACE_STANDARD.md. |
| Empty (нет сайтов в реестре) | `ui.Empty`(message="Подключите сайт через WordPress Hub, чтобы Internal Linking Engine мог его просканировать", icon="Link", action=`ui.Button`("Открыть WordPress Hub", on_click=ui.Navigate(...))) | Честная зависимость, не молчаливая пустота. |
| Empty (сайты есть, ни один не включён) | `ui.Empty`(message="Включите перелинковку для сайта", action=`ui.Button`("+ Включить сайт")→форма выбора сайта) | Прямой CTA, не общий текст. |
| Site Enable Form (center) | `ui.Form`(action="enable_site") с растянутым на всю ширину `ui.Stack`(align="stretch"): `ui.Stack`(v,gap=1,[`ui.Text`("Сайт", variant="caption"), `ui.Select`(param_name="site_id", placeholder="Выберите подключённый сайт", full_width=True)]), `ui.Stack`(v,gap=1,[`ui.Text`("Лимит ссылок на статью", variant="caption"), `ui.Input`(param_name="max_links_per_post", placeholder="напр. 3", full_width=True)]), `ui.Stack`(v,gap=1,[`ui.Text`("Языки сайта", variant="caption"), `ui.MultiSelect`(param_name="languages", placeholder="ru, ro — оставьте пустым для автоопределения", full_width=True)]), submit `ui.Button`(full_width=True, label="Включить и просканировать", loading_label="Сканируем…") | Каждое поле с лейблом через Stack+caption (L1), контекстуальный placeholder, форма растянута на всю ширину (§6 стандарта). |
| Site List (center) | `ui.DataTable`(columns: домен, статус `ui.Badge`, режим, дата последнего скана, действия `ui.Button`("Просканировать сейчас")/`ui.Button`("Настройки")) | Multi-site, как WordPress Hub/Content Strategy Hub. |
| Scan Progress (center, после enable_site/re-scan) | `ui.Alert`(variant="info", "Сканирование запущено в фоне — обновите статус через минуту") + `ui.Button`("Обновить статус", on_click=ui.Call("get_site_index_status", site_id=...)) | Честная эмуляция без живого push-прогресса (см. §0). |
| Linking Plan Preview (center, после preview_internal_links) | `ui.DataTable`(columns: статья, найденный текст, предложенный анкор→цель, тип [ссылка/CTA]) + `ui.Alert`(variant="warn", если план пуст/языки смешаны — не должно случаться, но alert на всякий случай) + `ui.Button`("Применить план", variant="primary", on_click=ui.Call("apply_internal_links", ...)) + `ui.Button`("Отклонить план", variant="secondary") | DataTable — единственный table-примитив; explicit apply/reject, не auto. |
| Run Dashboard (center) | `ui.DataTable`(columns: сайт, дата, добавлено ссылок, добавлено CTA, статус `ui.Badge`, `ui.Button`("Откатить")) | Дашборд прогонов из плана (§9 PREPARATION.md). |
| Site Settings (center, через "Настройки") | `ui.Form`(action="update_site_settings"): `ui.Stack`(v,[`ui.Text`("Режим работы", variant="caption"), `ui.Select`(param_name="mode", options=[{"value":"review_first","label":"Review-first (проверять перед применением)"},{"value":"full_auto","label":"Full-auto (применять автоматически)"}])]), `ui.Stack`(v,[`ui.Text`("Лимит ссылок на статью", variant="caption"), `ui.Input`(param_name="max_links_per_post", placeholder="напр. 3")]), `ui.Stack`(v,[`ui.Text`("Исключённые страницы (URL, по одной на строку)", variant="caption"), `ui.TextArea`(param_name="excluded_urls", placeholder="https://example.com/contacts", rows=4)]), `ui.Stat`(label="Подтверждений до Full-auto", value=..., trend_direction="up") | Настройки по сайту как в §9 PREPARATION.md; Select вместо несуществующего RadioGroup (см. UI_COMPONENT_VOCABULARY.md §4); Stat вместо несуществующего trust-виджета. |
| Confirm Rollback | `ui.Dialog`("Откатить этот прогон? Контент вернётся к состоянию до применения.", on_confirm=ui.Call("rollback_linking_run", ...)) | Единственный способ "Точно?"-паттерна — Dialog, не голая кнопка на деструктивное действие. |

## 2. Правило "без дублирования инструкций"

Кнопка "Применить план" в Linking Plan Preview не дублирует текст объяснения из
модалки подтверждения — сайдбар и center вообще не показывают отдельного описания
того, что делает apply/rollback: единственное развёрнутое объяснение — в самом
`ui.Dialog` подтверждения (для rollback) и в кратком `ui.Alert` перед применением
плана (для apply), нигде больше не повторяется.

## 3. Известные ограничения, применённые здесь

- L1 (нет `label=`) — везде `ui.Stack`+`ui.Text(variant="caption")` над полем.
- Форма enable_site и update_site_settings растянуты на всю ширину слота
  (`align="stretch"` на внешнем Stack, `full_width=True` на полях/кнопке) — по
  системному правилу форм подключения/настройки в сайдбаре/центре.
- L8 (`DataColumn` не заворачивается в список) — колонки передаются напрямую в
  `columns=[...]`.
- L6 (`Alert` только info/success/warn/error) — используются только эти варианты.
