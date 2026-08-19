# AI-first Development Pipeline — AS-IS Workflow & FSM v1.0

**Статус:** AS-IS  
**Версия:** 1.0

Документ фиксирует фактическое состояние существующего AI-first development pipeline на основании текущего кода и проведённого независимого ревью.

## 1. Назначение документа

Документ является AS-IS, а не проектом будущей архитектуры.

Он не содержит требований TO-BE, предложений по исправлению или архитектурных решений, если они не следуют непосредственно из зафиксированного поведения текущей реализации.

## 2. Контекст процесса

Текущий pipeline связывает:

```
Telegram
    ↓
GitHub Issue
    ↓
GitHub Copilot Coding Agent
    ↓
Pull Request
    ↓
CI
    ↓
Diff / Review
    ↓
Merge confirmation
    ↓
GitHub Merge
```

Основные компоненты процесса:

- Telegram как пользовательский control channel
- GitHub Issue как рабочая сущность задачи
- Copilot Coding Agent как исполнитель
- Pull Request как результат работы агента
- GitHub Actions / CI как источник результатов проверок
- Pipeline Job как локальное состояние orchestration
- GitHub как внешний источник состояния Issue / PR / CI

## 3. Главный AS-IS вывод

Фактическое состояние workflow определяется не только `JobState`.

Модель имеет три слоя:

```
┌──────────────────────────────────────┐
│             JobState                 │
│                                      │
│ TASK_ACCEPTED                        │
│ CODING_AGENT_RUNNING                 │
│ WAIT_TESTS                           │
│ TEST_PASSED                          │
│ MERGE_CONFIRMATION_PENDING           │
│ DONE / FAILED / ADAPTER_ERROR        │
└──────────────────┬───────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
 Job workflow flags      GitHub state
        │                     │
        └──────────┬──────────┘
                   ▼
          фактическое поведение
```

В объекте `Job` одновременно хранятся `state`, `awaiting_user_reply`, notification flags, `state_before_merge` и `merge_head_sha`.

Следовательно, описание «`JobState` является полной моделью процесса» не соответствует фактическому поведению текущего кода.

## 4. JobState Inventory

| State | Фактическое значение | Terminal |
| --- | --- | --- |
| `TASK_ACCEPTED` | Job создана и ожидает первичного запуска Coding Agent | Нет |
| `CODING_AGENT_RUNNING` | Coding Agent выполняет задачу либо fix iteration | Нет |
| `WAIT_TESTS` | PR создан, pipeline ожидает результат CI | Нет |
| `TEST_PASSED` | CI прошёл и пользователю сообщено о готовности к diff/merge | Нет |
| `MERGE_CONFIRMATION_PENDING` | Пользователь вызвал `/merge`, условия прошли, ожидается подтверждение кнопкой | Нет |
| `DONE` | Pipeline считает Job завершённой | Да |
| `FAILED` | Предыдущая активная Job остановлена при запуске новой Job | Да |
| `ADAPTER_ERROR` | Ошибка создания/назначения задачи через adapter | Да |

Terminal states определены непосредственно в `JobState.terminal()`: `DONE`, `FAILED`, `ADAPTER_ERROR`.

## 5. Основная FSM

```
                         ┌─────────────────┐
                         │ TASK_ACCEPTED   │
                         └────────┬────────┘
                                  │
                         create/assign
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
                    ▼                           ▼
       CODING_AGENT_RUNNING              ADAPTER_ERROR
                    │
                 PR_OPENED
                    │
                    ▼
               WAIT_TESTS
                 │       │
      TESTS_PASSED      TESTS_FAILED
                 │       │
                 ▼       ▼
          TEST_PASSED   CODING_AGENT_RUNNING
                 │
               /merge
                 │
                 ▼
      MERGE_CONFIRMATION_PENDING
              │           │
           Merge        Cancel
              │           │
              ▼           ▼
            DONE     state_before_merge
```

Дополнительный переход:

```
any non-terminal
      │
    /new
      ▼
    FAILED
```

## 6. TASK_ACCEPTED

После `/new` создаётся новый Job со значением:

```
state = TASK_ACCEPTED
```

Затем `_process_state()` сразу выполняет создание Issue и запуск Coding Agent.

При успешном запуске:

```
TASK_ACCEPTED
      ↓
CODING_AGENT_RUNNING
```

При ошибке:

```
TASK_ACCEPTED
      ↓
ADAPTER_ERROR
```

При запуске новой Job существующая non-terminal Job переводится в `FAILED`, её watchers останавливаются.

## 7. CODING_AGENT_RUNNING

Состояние используется одновременно для:

- первоначальной работы Coding Agent
- последующих fix iterations после падения CI

Состояние само по себе не означает отдельную фазу внутри `_process_state()`: дальнейшее продвижение происходит через `process_event()`.

При `PR_OPENED`:

```
CODING_AGENT_RUNNING
      ↓
WAIT_TESTS
```

При `TESTS_FAILED`:

```
CODING_AGENT_RUNNING
      ↓
trigger_fix_iteration()
      ↓
CODING_AGENT_RUNNING
```

## 8. WAIT_TESTS

`PR_OPENED` устанавливает:

- `pr_number`
- `pr_url`
- `state = WAIT_TESTS`

и сбрасывает `awaiting_user_reply`.

Затем pipeline ожидает событий CI.

При `TESTS_PASSED`:

```
WAIT_TESTS
      ↓
TEST_PASSED
```

При `TESTS_FAILED` запускается fix iteration:

```
WAIT_TESTS
      ↓
CODING_AGENT_RUNNING
```

## 9. TEST_PASSED

При `TESTS_PASSED` Job переводится в `TEST_PASSED`.

После этого `_process_state()` выполняет:

- публикацию pipeline-check comment
- уведомление пользователя
- сообщение о доступности `/diff` и `/merge`

`pipeline_check_posted` предотвращает повторное выполнение этого блока после того, как flag установлен.

Текущее состояние поэтому означает не просто «CI сейчас green».

Фактически оно означает: pipeline обработал событие успешного CI и перешёл в состояние, из которого разрешается дальнейшая работа с PR.

## 10. MERGE_CONFIRMATION_PENDING

`/merge` сначала выполняет `_evaluate_merge()`.

Проверяются:

- наличие PR
- merged/closed состояние
- ожидание ответа Copilot
- CI
- mergeability
- mergeable state

Если всё разрешено:

```
state_before_merge = текущий state
merge_head_sha = текущий HEAD SHA
state = MERGE_CONFIRMATION_PENDING
```

После этого пользователю отправляются кнопки:

- Merge
- Cancel

## 11. Merge confirmation

При нажатии Merge pipeline:

- проверяет права оператора
- проверяет `MERGE_CONFIRMATION_PENDING`
- повторно выполняет `_evaluate_merge()`
- проверяет актуальный HEAD SHA
- выполняет GitHub merge с pinned SHA
- переводит Job в `DONE`

То есть merge является двухфазным:

```
/merge
   ↓
evaluation
   ↓
confirmation pending
   ↓
fresh evaluation
   ↓
HEAD verification
   ↓
GitHub merge
   ↓
DONE
```

## 12. Cancel

При Cancel:

```
MERGE_CONFIRMATION_PENDING
        ↓
state_before_merge
```

Затем:

```
state_before_merge = None
merge_head_sha = None
```

и Job сохраняется.

Однако существует подтверждённый edge case:

```
TEST_PASSED
    ↓ /merge
MERGE_CONFIRMATION_PENDING
    ↓ /merge повторно
MERGE_CONFIRMATION_PENDING
    ↓ Cancel
MERGE_CONFIRMATION_PENDING
```

Причина — повторный `/merge` записывает текущий `MERGE_CONFIRMATION_PENDING` в `state_before_merge`.

Классификация: **CONFIRMED BUG**.

## 13. DONE

Job переводится в `DONE` в двух основных случаях.

### Собственный merge

```
confirm_merge
    ↓
GitHub merge
    ↓
DONE
```

### Обнаруженный внешний merge

Если `/diff` или `/merge` обнаруживает `pr.merged == true`, вызывается `_mark_observed_merged()`:

```
JobState → DONE
```

## 14. FAILED

Текущее значение `FAILED` имеет специальную семантику.

При запуске нового `/new`:

```
active Job
    ↓
FAILED
```

То есть `FAILED` в текущей реализации означает: Job была принудительно остановлена запуском новой задачи.

Это не эквивалентно «Coding Agent failed».

## 15. ADAPTER_ERROR

При ошибке создания Issue или назначения Coding Agent:

```
TASK_ACCEPTED
      ↓
ADAPTER_ERROR
```

Состояние terminal, watchers останавливаются.

## 16. Orthogonal workflow state

### 16.1 `awaiting_user_reply`

При `COPILOT_QUESTION` устанавливается:

```
awaiting_user_reply = true
```

При следующих событиях flag сбрасывается:

- `AGENT_STARTED`
- `PR_OPENED`
- `AGENT_COMPLETED`
- `TESTS_FAILED`

При `awaiting_user_reply=True` `_evaluate_merge()` запрещает merge.

Следовательно, `JobState` + `awaiting_user_reply` определяет фактическое разрешение `/merge`.

## 17. Notification / idempotency flags

В Job присутствуют:

- `agent_started_notified`
- `agent_completed_notified`
- `pipeline_check_posted`
- `issue_closed_notified`

Они предотвращают повторные уведомления/действия.

При этом они не являются отдельными `JobState`.

Особенно важно: `pipeline_check_posted` и `agent_completed_notified` не сбрасываются при переходе в новую fix iteration.

Следовательно, текущая модель трактует их как состояние всей Job, а не отдельной iteration.

Является ли это дефектом процесса — в AS-IS не определяется.

## 18. Event Matrix

| Event | Действие |
| --- | --- |
| `AGENT_STARTED` | снимает `awaiting_user_reply`, уведомляет один раз |
| `COPILOT_QUESTION` | устанавливает `awaiting_user_reply`, уведомляет |
| `PR_OPENED` | записывает PR, переводит Job в `WAIT_TESTS` |
| `AGENT_COMPLETED` | снимает ожидание, уведомляет один раз |
| `TESTS_PASSED` | переводит в `TEST_PASSED` |
| `TESTS_FAILED` | запускает `trigger_fix_iteration`, переводит в `CODING_AGENT_RUNNING` |
| `ISSUE_CLOSED` | уведомляет, но `JobState` не меняет |

## 19. Важное асимметричное поведение CI

Текущая реализация допускает:

```
MERGE_CONFIRMATION_PENDING
       │
       ├── TESTS_PASSED → ignore
       │
       └── TESTS_FAILED → CODING_AGENT_RUNNING
```

То есть `TESTS_FAILED` обрабатывается шире, чем `TESTS_PASSED`.

Это подтверждённое AS-IS поведение.

При этом пользователь может уже иметь активные кнопки Merge/Cancel.

Классификация: **CONFIRMED AS-IS / critical process inconsistency**.

## 20. Merge rejection после confirmation

Если между `/merge` и подтверждением:

- CI стал failing
- PR стал closed
- Copilot снова ожидает пользователя
- PR перестал быть mergeable

повторная `_evaluate_merge()` возвращает `allowed=False`.

При этом текущий код не вызывает `_revert_merge_pending()` для этих отказов.

Следовательно:

```
MERGE_CONFIRMATION_PENDING
       ↓
confirm
       ↓
decision.allowed = false
       ↓
MERGE_CONFIRMATION_PENDING
```

Состояние остаётся pending.

Классификация: **CONFIRMED AS-IS behavior / потенциальный dead-end**.

## 21. GitHub как внешний state

Pipeline хранит локальное состояние Job, но при операциях с PR повторно обращается к GitHub.

Используются внешние признаки:

**Issue**

- open / closed

**PR**

- open / closed / merged
- draft
- `head_sha`
- `mergeable`
- `mergeable_state`

**CI**

- queued
- in_progress
- waiting
- completed
- conclusion

Таким образом возможна временная комбинация:

```
GitHub:
PR = MERGED

Pipeline:
Job = TEST_PASSED
```

пока pipeline не выполнит reconciliation.

## 22. CI AS-IS

Текущий `_fresh_ci_status()` ищет Actions runs по `pr.head_ref` и выбирает completed run из найденного списка.

При этом код не устанавливает отдельную модель:

```
PR HEAD SHA
    ↓
конкретный required workflow/check
```

как authoritative CI contract.

AS-IS:

```
PR branch
   ↓
Actions workflow runs
   ↓
completed run
   ↓
conclusion
```

Вопрос «какой CI run является authoritative при наличии нескольких workflows/runs?» остаётся **UNDEFINED**.

## 23. Подтверждённый CI BUG

При `GitHubForbiddenError` в `_fresh_ci_status()` код возвращает `"success"`, а не `pending` или `unknown`.

Фактическая цепочка:

```
Actions API 403
      ↓
CI status = "success"
      ↓
_evaluate_merge()
      ↓
CI failure не блокирует merge
```

Классификация: **CONFIRMED BUG — HIGH**.

## 24. Event idempotency

Pipeline использует `processed_event_ids` для подавления повторных событий.

Однако при достижении более 10 000 IDs множество очищается:

```
processed_event_ids.clear()
```

После этого старый event ID теоретически может быть обработан повторно.

AS-IS: это не абсолютная идемпотентность, а ограниченная дедупликация с eviction.

## 25. Recovery после restart

`recover_active_jobs()`:

- загружает non-terminal Jobs
- восстанавливает сохранённые event IDs
- уведомляет пользователя
- восстанавливает watchers
- повторно запускает `_process_state()` для `TASK_ACCEPTED`

Для:

- `CODING_AGENT_RUNNING`
- `WAIT_TESTS`
- `TEST_PASSED`
- `MERGE_CONFIRMATION_PENDING`

watchers запускаются заново.

Но recovery не выполняет непосредственную reconciliation:

```
MERGE_CONFIRMATION_PENDING
+
PR already merged
```

с GitHub.

Поэтому Job может временно остаться в `MERGE_CONFIRMATION_PENDING`.

AS-IS behavior; recovery contract не определён полностью.

## 26. Watchdog

Stale watchdog работает для:

- `CODING_AGENT_RUNNING`
- `WAIT_TESTS`

и при отсутствии событий только отправляет уведомление.

Он не меняет `JobState`.

Состояния `_stale_notified` и `_watch_error_notified` хранятся в памяти процесса и теряются после restart.

## 27. Новый `/new`

Если уже существует active Job:

```
/new
   ↓
previous.state = FAILED
   ↓
watchers stop
   ↓
new Job
```

Одновременно существует только одна активная Job на chat.

Это часть фактического AS-IS процесса.

## 28. Telegram command FSM

| Команда | AS-IS |
| --- | --- |
| `/new <text>` | создаёт новую Job, предыдущую active переводит в `FAILED` |
| `/status` | показывает состояние/ссылки |
| `/diff` | получает актуальный diff связанного PR |
| `/merge` | выполняет merge evaluation и создаёт confirmation |
| Merge callback | повторно проверяет условия и выполняет merge |
| Cancel callback | возвращает `state_before_merge` |

`/merge` и `/diff` работают с PR, связанным с Job.

## 29. Внешний merge

Внешний merge GitHub может быть обнаружен через `/diff` или `/merge`.

При обнаружении `pr.merged == true` pipeline переводит Job в `DONE`.

Таким образом внешний GitHub event не обязательно непосредственно вызывает transition в Job FSM.

Это reconciliation on demand.

## 30. AS-IS Problems Classification

### CONFIRMED BUG

**B1. Повторный `/merge`**

```
PENDING
 → /merge
 → PENDING
 → Cancel
 → PENDING
```

`state_before_merge` может содержать `MERGE_CONFIRMATION_PENDING`.

**B2. Actions API 403 трактуется как CI success**

```
CI unknown
 → "success"
 → merge gate может пройти
```

### CONFIRMED AS-IS / Critical

| ID | Поведение |
| --- | --- |
| A1 | `TESTS_FAILED` разрешён из `MERGE_CONFIRMATION_PENDING` |
| A2 | CI/PR отказ во время confirmation не обязательно выводит Job из pending |
| A3 | `pipeline_check_posted` относится ко всей Job и не сбрасывается при fix iteration |
| A4 | `agent_completed_notified` относится ко всей Job и не сбрасывается при fix iteration |
| A5 | `ISSUE_CLOSED` уведомляет, но не меняет `JobState` |
| A6 | `FAILED` используется для вытеснения предыдущей Job |
| A7 | External merge обнаруживается при отдельных reconciliation operations |
| A8 | CI не имеет явно определённого authoritative workflow/check при нескольких runs |
| A9 | Event deduplication имеет лимит 10 000 IDs |

## 31. UNDEFINED

Следующие вопросы не должны решаться внутри AS-IS документа:

1. Какой CI run является authoritative.
2. Что делать с pending confirmation после restart и external merge.
3. Что делать при нескольких PR на один Issue.
4. Приоритет webhook и polling при конфликтующих событиях.
5. Относятся ли notification flags к Job или iteration.
6. Какой источник состояния имеет приоритет после downtime.
7. Что должно происходить с Job при `ISSUE_CLOSED`.

Это вопросы для проектирования TO-BE, а не утверждения о текущей реализации.

## 32. SUSPICIOUS

### S1. Concurrent lost update

В коде есть asynchronous operations между чтением и сохранением Job, но по имеющимся материалам нельзя доказать полноценный lost-update сценарий без подтверждения semantics конкретного repository/storage.

Поэтому это SUSPICIOUS, а не BUG.

### S2. Старые event IDs после eviction

Может возникнуть повторная обработка очень старого event.

### S3. In-memory watchdog flags

После restart `_stale_notified` и `_watch_error_notified` сбрасываются.

## 33. Финальная модель AS-IS

Для дальнейшей работы предлагается считать подтверждённой следующую модель:

```
                         ┌─────────────────────┐
                         │      Telegram       │
                         │ commands/callbacks  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   PipelineRunner    │
                         │                     │
                         │   JobState FSM      │
                         │        +            │
                         │ workflow flags      │
                         └──────────┬──────────┘
                                    │
                      ┌─────────────┴─────────────┐
                      │                           │
                      ▼                           ▼
              ┌──────────────┐           ┌──────────────┐
              │ Copilot Agent│           │    GitHub    │
              │              │           │              │
              │ Issue events │           │ Issue / PR   │
              │ Agent events │           │ CI / Merge   │
              └──────────────┘           └──────┬───────┘
                                                │
                                                ▼
                                         reconciliation
```

Именно эта модель должна считаться базовой AS-IS точкой, от которой дальше проектируется TO-BE.

## Статус документа

| Область | Статус |
| --- | --- |
| AS-IS FSM | восстановлена |
| JobState | подтверждён по коду |
| Events | подтверждены по обработчику `process_event()` |
| Telegram control flow | подтверждён |
| Merge flow | подтверждён |
| External GitHub state | зафиксирован |
| Hidden/orthogonal state | зафиксирован |
| Confirmed bugs | 2 |
| Critical AS-IS behaviors | 9 |
| Undefined areas | 7 |
| TO-BE решения | намеренно не включены |
