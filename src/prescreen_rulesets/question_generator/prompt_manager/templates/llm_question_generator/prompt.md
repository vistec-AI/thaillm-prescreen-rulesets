Below is the patient's prescreening Q&A history, grouped by phase.

{% for phase_num, pairs in grouped_pairs.items() %}
{% if phase_num == 0 %}
## Phase 0: Demographics
*Basic patient profile — age, gender, underlying conditions. Use this to contextualize risk factors.*

{% elif phase_num == 1 %}
## Phase 1: ER Critical Screen
*11 critical yes/no checks. All items shown here are NEGATIVE — the patient cleared the ER critical screen. If any had been positive, the patient would have been routed to ER immediately.*

{% elif phase_num == 2 %}
## Phase 2: Symptom Selection
*The patient's chief complaint from the NHSO symptom list.*

{% elif phase_num == 3 %}
## Phase 3: ER Checklist (positive findings only)
*Symptom-specific emergency red flags. Only POSITIVE findings are shown below — negative items have been omitted. These findings may indicate higher acuity.*

{% elif phase_num == 4 %}
## Phase 4: OLDCARTS
*Detailed symptom characterization (Onset, Location, Duration, Character, Aggravating, Relieving, Timing, Severity). The patient has already answered these — do NOT re-ask these topics.*

{% elif phase_num == 5 %}
## Phase 5: OPD
*Additional outpatient-directed questions for department routing and severity assessment.*

{% else %}
## Phase {{ phase_num }}
{% endif %}

{% for pair in pairs %}
- **Q:** {{ pair.question }}
  **A:** {{ pair.answer | tojson }}
{% endfor %}

{% endfor %}
{% if grouped_pairs %}
---

**Instructions:** Based on the above history, generate up to **5** follow-up questions that go BEYOND what OLDCARTS and the ER checklists have already captured. Focus on questions that lead to better clues for differential diagnosis:
- Red flags specific to this patient's presentation
- Questions that discriminate between the top differential diagnoses
- Comorbidity interactions and medication history
- Functional impact and symptom progression
- Related organ system symptoms

**Order questions by clinical importance** — put the most diagnostically valuable question first.

Do NOT ask about onset, location, duration, character, aggravating/relieving factors, timing, or severity — these are already covered in Phase 4.
Do NOT ask for vital signs or physical measurements (blood pressure, heart rate, temperature, SpO2, etc.) — these will be collected by medical staff.
{% else %}
No prescreening history is available yet. Generate general follow-up questions to begin the clinical assessment.
{% endif %}
