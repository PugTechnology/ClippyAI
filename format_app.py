import re

with open("app.py", "r") as f:
    code = f.read()

# Fix the specific string formatting issues that were causing problems
code = code.replace('\\n', '\n')
# We actually WANT real newlines in the string but let's just use regular python formatting properly

code = code.replace('return "\n".join(paths)', 'return "\\n".join(paths)')
code = code.replace('plan_steps = "\n".join([f"1. {step}" for step in plan_data.get("plan", [])])', 'plan_steps = "\\n".join([f"1. {step}" for step in plan_data.get("plan", [])])')
code = code.replace('files_to_change = "\n".join([f"- {f}" for f in plan_data.get("files_to_change", [])])', 'files_to_change = "\\n".join([f"- {f}" for f in plan_data.get("files_to_change", [])])')
code = code.replace('risks = "\n".join([f"- {r}" for r in plan_data.get("risks", [])])', 'risks = "\\n".join([f"- {r}" for r in plan_data.get("risks", [])])')
code = code.replace('f"### 🧠 Analyst Plan Generated\n\n"', 'f"### 🧠 Analyst Plan Generated\\n\\n"')
code = code.replace('f"**Analysis:** {plan_data.get(\'analysis\')}\n"', 'f"**Analysis:** {plan_data.get(\'analysis\')}\\n"')
code = code.replace('f"**Estimated Complexity:** {plan_data.get(\'estimated_complexity\')}\n\n"', 'f"**Estimated Complexity:** {plan_data.get(\'estimated_complexity\')}\\n\\n"')
code = code.replace('f"#### Files to Modify:\n{files_to_change}\n\n"', 'f"#### Files to Modify:\\n{files_to_change}\\n\\n"')
code = code.replace('f"#### Execution Plan:\n{plan_steps}\n\n"', 'f"#### Execution Plan:\\n{plan_steps}\\n\\n"')
code = code.replace('f"#### Instructions for Coder:\n{plan_data.get(\'coder_instructions\')}\n\n"', 'f"#### Instructions for Coder:\\n{plan_data.get(\'coder_instructions\')}\\n\\n"')
code = code.replace('f"#### Potential Risks:\n{risks}\n\n"', 'f"#### Potential Risks:\\n{risks}\\n\\n"')
code = code.replace('{"body": f"### 🧠 Analyst Note\n\n{reason}"}', '{"body": f"### 🧠 Analyst Note\\n\\n{reason}"}')

with open("app.py", "w") as f:
    f.write(code)

code = code.replace('issues_md = "\n".join([f"- ❌ {issue}" for issue in review_data.get("issues", [])])', 'issues_md = "\\n".join([f"- ❌ {issue}" for issue in review_data.get("issues", [])])')
code = code.replace('suggestions_md = "\n".join([f"- 💡 {sug}" for sug in review_data.get("suggestions", [])])', 'suggestions_md = "\\n".join([f"- 💡 {sug}" for sug in review_data.get("suggestions", [])])')
code = code.replace('f"### 🤖 Watchdog Review (Attempt {attempts + 1}/{MAX_RETRIES})\n\n"', 'f"### 🤖 Watchdog Review (Attempt {attempts + 1}/{MAX_RETRIES})\\n\\n"')
code = code.replace('f"**Verdict:** {review_data.get(\'verdict\')}\n"', 'f"**Verdict:** {review_data.get(\'verdict\')}\\n"')
code = code.replace('f"**Score:** {review_data.get(\'score\')}/10\n\n"', 'f"**Score:** {review_data.get(\'score\')}/10\\n\\n"')
code = code.replace('f"#### Required Changes:\n{issues_md}\n\n"', 'f"#### Required Changes:\\n{issues_md}\\n\\n"')
code = code.replace('f"#### Suggestions:\n{suggestions_md}\n\n"', 'f"#### Suggestions:\\n{suggestions_md}\\n\\n"')

with open("app.py", "w") as f:
    f.write(code)
