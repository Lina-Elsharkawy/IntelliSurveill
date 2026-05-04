from intent_router import _layer1_deterministic

tests = [
    # Small talk
    ('hello', 'small_talk'),
    ('what can you do', 'small_talk'),
    # Registry
    ('list to me the names of the known people', 'all_known_people'),
    ('show me the employees', 'all_known_people'),
    ('who are the employees', 'all_known_people'),
    ('list visitors', 'all_known_people'),
    ('who do we know', 'all_known_people'),
    # Record counts
    ('how many entry logs do we have', 'table_record_counts'),
    ('how many cameras are there', 'table_record_counts'),
    ('how many records in each table', 'table_record_counts'),
    ('which table has the most records', 'table_record_counts'),
    # Detection counts
    ('how many unknown was detected in 29 april', 'unknown_detection_count'),
    ('how many known was detected in 29 april', 'known_face_detection_count'),
    ('how many people were detected today', 'face_detection_count'),
    # People
    ('who was seen today', 'people_seen_on_date'),
    ('who was seen yesterday', 'people_seen_on_date'),
    ('who came in last monday', 'people_seen_on_date'),
    # Person intents - Layer 1 with name extraction
    ('where was maged last seen', 'person_last_seen'),
    ('find lina', 'person_last_seen'),
    ('locate sara', 'person_last_seen'),
    ('first time arwa was seen', 'person_first_seen'),
    ('when was lina first detected', 'person_first_seen'),
    ('show maged timeline yesterday', 'person_timeline'),
    ('track lina last monday', 'person_timeline'),
    # Unknown face events
    ('show latest unknown face events', 'latest_unknown_face_events'),
    ('list unknowns', 'latest_unknown_face_events'),
    ('show unreviewed unknowns', 'latest_unknown_face_events'),
    # Event ID intents
    ('investigate unknown event 5', 'investigate_unknown_face_event'),
    ('find similar faces to event 5', 'similar_unknown_faces'),
    # Anomalies
    ('show latest anomalies', 'latest_anomalies'),
    ('show anomaly logs', 'latest_anomalies'),
    ('anomalies near maged', 'anomalies_near_person'),
    ('any incidents near event 12', 'anomalies_near_unknown_event'),
    # Summaries
    ('give me a security summary', 'daily_security_summary'),
    ('daily report', 'daily_security_summary'),
    ('camera activity summary', 'camera_activity_summary'),
    ('busiest camera today', 'camera_activity_summary'),
    # Repeated unknowns
    ('did any stranger come back', 'repeated_unknown_faces'),
    ('repeated unknown visitors', 'repeated_unknown_faces'),
]

passed = failed = 0
for q, expected in tests:
    r = _layer1_deterministic(q)
    if r is not None and r['intent'] == expected:
        passed += 1
    else:
        failed += 1
        print(f'FAIL: {q!r}')
        got = r["intent"] if r is not None else "None (Fell through to Layer 2)"
        print(f'  expected={expected}, got={got}')

print(f'\n{passed}/{passed+failed} passed - Layer 1 coverage only (no LLM needed)')
