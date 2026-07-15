"""
A "Ponte" (bridge): orquestra uma conversa entre 2+ agentes de IA e,
opcionalmente, um humano.

Como cada modelo só entende uma conversa de duas partes (user/assistant),
montamos, para cada agente na sua vez de falar, uma lista de mensagens
onde:
  - as falas dele mesmo em turnos anteriores viram role "assistant";
  - todas as outras falas (do humano ou de outros agentes) viram role
    "user", prefixadas com "[Nome do autor]:" para que o agente saiba
    quem disse o quê.
Um system prompt explica esse formato para o modelo.
"""

BRIDGE_SYSTEM_PROMPT = (
    "Você está participando de uma conversa em grupo, com um usuário humano e "
    "possivelmente outros assistentes de IA. Cada mensagem anterior é marcada com "
    "o nome de quem a enviou, no formato '[Nome]: mensagem'. Responda de forma natural "
    "e direta ao ponto: pode concordar, discordar, complementar ou questionar o que "
    "os outros participantes disseram, e pode se dirigir a eles pelo nome quando fizer "
    "sentido. Não repita o formato '[Nome]:' na sua própria resposta, apenas escreva sua fala."
)


def build_messages_for_turn(transcript: list, current_slug: str) -> list:
    """
    transcript: lista de dicts {speaker, agent_slug (None se humano), content}
    current_slug: slug do agente que está prestes a falar agora
    """
    messages = [{"role": "system", "content": BRIDGE_SYSTEM_PROMPT}]
    for turn in transcript:
        if turn.get("agent_slug") == current_slug:
            messages.append({"role": "assistant", "content": turn["content"]})
        else:
            messages.append({"role": "user", "content": f"[{turn['speaker']}]: {turn['content']}"})
    return messages
