from openai import OpenAI
client = OpenAI()

response = client.responses.create(
    model="gpt-5",
    input="SM-3/6 유도탄 제원을 제출해줘."
)

print(response.output_text)