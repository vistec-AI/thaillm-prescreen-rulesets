You are given a structured patient case for hospital triage.

## Patient Profile

### Demographics
- Age: {{age}}
- Gender: {{gender}}
- Height: {{height}} cm
- Weight: {{weight}} kg
- Occupation: {{occupation}}

### Presenting Problem
- Chief Complaint: {{complaint}}
- Primary Symptom: {{primary_symptom}}
- Secondary Symptoms: {{secondary_symptoms}}

### History of Present Illness (OLDCART)
- Onset: {{oldcart_onset}}
- Location: {{oldcart_location}}
- Duration: {{oldcart_duration}}
- Characteristics: {{oldcart_characteristic}}
- Aggravating Factors: {{oldcart_aggravating}}
- Relieving Factors: {{oldcart_relieving}}
- Timing: {{oldcart_timing}}
- Severity: {{oldcart_severity}}

### Past Medical History
- Underlying Diseases: {{underlying_diseases}}
- Medical History: {{medical_history}}
- Current Medication: {{current_medication}}
- Allergies: {{drug_food_allergies}}
- Surgical History: {{surgical_history}}

## Conversation History
{{conversation}}

## Task
Using both the structured patient profile and the conversation history:

1. Infer the single most likely primary disease or diagnosis.
2. Choose the single most appropriate hospital department for routing.
3. Choose the triage severity level.

## Important Rules
- Use the conversation history to refine or update the structured profile if newer details appear there.
- Prioritize urgent or dangerous conditions when symptoms suggest possible emergency illness.
- Do not invent facts that are not supported by the profile or conversation.
- If information is incomplete, choose the most likely answer based on the available evidence.
- Output only the final answer in the required XML format.