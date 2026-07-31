from .config import STATES, STATE_TRANSITIONS


class ConversationStateMachine:
    def __init__(self, memory_system=None):
        self.current_state = "greeting"
        self.turns_in_state = 0
        self.total_turns = 0
        self.state_history = []
        self.memory = memory_system
        self.trust_threshold_met = False
        self.avoidance_count = 0
        self.deep_investigation_questions = 0
        self.free_conversation_turns = 0
        self.selected_pillar = None
        self.insight_delivered = False
        self.routine_created = False
        self.pillar_exit_explicitly = False

    def transition(self, emotion_result=None, user_message=""):
        config = STATE_TRANSITIONS.get(self.current_state, {})
        next_state = self._evaluate_transition(emotion_result, user_message)
        if next_state and next_state != self.current_state:
            self.state_history.append(self.current_state)
            self.current_state = next_state
            self.turns_in_state = 0
            if next_state == "deep_investigation":
                self.deep_investigation_questions = 0
        else:
            self.turns_in_state += 1

        self.total_turns += 1
        return self.current_state

    def _evaluate_transition(self, emotion_result, user_message):
        state = self.current_state
        turns = self.turns_in_state
        config = STATE_TRANSITIONS.get(state, {})

        if state == "greeting":
            words = user_message.strip().split()
            if len(words) > 2 and self._has_topic_signal(user_message):
                return "guided_discovery"
            if len(words) > 2:
                return "free_conversation"
            if turns >= 1:
                return "free_conversation"
            return None

        if state == "free_conversation":
            self.free_conversation_turns += 1

            # Anger is NOT avoidance: a frustrated user is engaged, not deflecting
            if emotion_result and (emotion_result.get("primary_emotion") == "angry"
                                   or emotion_result.get("frustration", 0) > 50):
                return "guided_discovery"

            if emotion_result and emotion_result.get("avoidance", 0) > 50:
                return "avoidance_detection"

            if self._has_topic_signal(user_message):
                return "guided_discovery"

            if emotion_result:
                intensity = emotion_result.get("emotional_intensity", 0)
                if intensity > 50:
                    return "guided_discovery"

            if self.free_conversation_turns >= 2:
                return "guided_discovery"
            return None

        if state == "rapport_building":
            trust_score = self.memory.get_trust_score() if self.memory else 30
            if trust_score >= 50:
                return "free_conversation"
            if emotion_result and emotion_result.get("engagement", 0) > 65:
                return "free_conversation"
            if turns >= 4:
                return "free_conversation"
            return None

        if state == "avoidance_detection":
            # Frustration/anger means the user IS engaged — de-escalate toward real work
            if emotion_result and (emotion_result.get("primary_emotion") == "angry"
                                   or emotion_result.get("frustration", 0) > 50):
                return "guided_discovery"
            if emotion_result and emotion_result.get("avoidance", 0) > 50:
                self.avoidance_count += 1
            else:
                self.avoidance_count = 0
            if self.avoidance_count >= 2:
                return "soft_exploration"
            if turns >= 3:
                return "free_conversation"
            return None

        if state == "soft_exploration":
            if emotion_result and emotion_result.get("engagement", 0) > 50:
                return "guided_discovery"
            if turns >= 3:
                return "free_conversation"
            return None

        if state == "guided_discovery":
            if self.selected_pillar:
                return "deep_investigation"
            if self._has_pillar_signal(user_message):
                return "pillar_selection"
            if turns >= 4:
                return "free_conversation"
            return None

        if state == "pillar_selection":
            if self.selected_pillar:
                return "deep_investigation"
            if turns >= 2:
                return "guided_discovery"
            return None

        if state == "deep_investigation":
            self.deep_investigation_questions += 1
            if self.pillar_exit_explicitly:
                return "insight_generation"
            if self.deep_investigation_questions >= 5:
                return "insight_generation"
            return None

        if state == "insight_generation":
            if self.insight_delivered:
                return "routine_planning"
            if turns >= 3:
                return "routine_planning"
            return None

        if state == "routine_planning":
            if self.routine_created or turns >= 4:
                return "reflection"
            return None

        if state == "reflection":
            if turns >= 2:
                return "follow_up"
            return None

        if state == "weekly_review":
            return "free_conversation"

        if state == "follow_up":
            return "free_conversation"

        return None

    def _has_topic_signal(self, message):
        topic_words = ["work", "sleep", "stress", "relation", "friend", "family",
                       "exercise", "health", "mood", "feel", "anxious", "worry",
                       "happy", "sad", "lonely", "tired", "eat", "food", "routine"]
        message_lower = message.lower()
        return any(tw in message_lower for tw in topic_words)

    def _has_pillar_signal(self, message):
        from .config import PILLARS
        message_lower = message.lower()
        for pillar in PILLARS:
            if pillar in message_lower:
                return True
        return False

    def select_pillar(self, pillar):
        self.selected_pillar = pillar
        if self.current_state == "guided_discovery":
            self.current_state = "pillar_selection"

    def mark_pillar_exit(self):
        self.pillar_exit_explicitly = True

    def mark_insight_delivered(self):
        self.insight_delivered = True

    def mark_routine_created(self):
        self.routine_created = True

    def get_state_info(self):
        return {
            "current_state": self.current_state,
            "turns_in_state": self.turns_in_state,
            "total_turns": self.total_turns,
            "state_history": self.state_history,
            "selected_pillar": self.selected_pillar,
            "insight_delivered": self.insight_delivered,
            "routine_created": self.routine_created
        }

    def set_state(self, state):
        if state in STATES:
            self.state_history.append(self.current_state)
            self.current_state = state
            self.turns_in_state = 0
