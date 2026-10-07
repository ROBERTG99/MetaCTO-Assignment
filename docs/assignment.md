Technical AI Assessment
Overview
This assessment evaluates your ability to design, build, and ship a functional product feature using AI-assisted development.
We are interested in more than just the final implementation. We want to understand how you leverage AI tools throughout the development process, make architectural decisions, balance technical tradeoffs, and think about building production-ready software.
Setup Instructions
1. Create a Public Git Repository
2. Set Up Your Development Environment
3. Configure Claude Code (or your AI tool of choice): Before writing any code, open Claude Code in your project root and use the following as your first prompt: "Create a CLAUDE.md file in the project root with the following instruction: # Project Rules ## Prompt Logging Every time you receive a new instruction or prompt, append it to prompts.txt in the project root with a timestamp (ISO 8601) and a brief summary of what you did in response. Create the file if it doesn't exist. Keep this log updated throughout all sessions." This sets up automatic prompt logging so we can see how you collaborated with the AI throughout the session.
Assignment
Product teams receive feature requests from customers, prospects, support teams, and internal stakeholders. As request volume grows, teams struggle to:
* Identify duplicate or related requests
* Understand the underlying customer problems
* Separate popular requests from strategically valuable ones
* Prioritize requests consistently
* Keep stakeholders informed about decisions and progress
* Spend less time manually reviewing, organizing, and summarizing feedback
Design and build an AI-first Feature Intelligence System that helps a product team turn unstructured feature requests into clear, actionable product decisions.
Your solution should allow users to submit and discover feature requests, but you should determine how AI can fundamentally improve the workflow. AI should be a core part of how the system solves the business problem.
Core Requirements
At a minimum, users should be able to:
* Submit a feature request with a title and description
* View and discover existing requests
* Express interest in or support for a request
* Understand how requests are being grouped, evaluated, or prioritized
You may modify or extend the traditional feature-voting experience if you believe another approach better addresses the business problem.
AI First Solution
Identify a high-value point in the feature-request lifecycle and design an AI-powered solution around it.
Your solution might:
* Detect and consolidate duplicate requests
* Identify the underlying need behind a proposed feature
* Group feedback into themes
* Enrich requests with customer or business context
* Recommend priorities using defined business criteria
* Automate triage and routing
* Surface emerging customer needs
* Generate decision briefs for product leaders
* Help communicate decisions back to stakeholders
The specific implementation is up to you. Be prepared to explain in your Loom:
* Which business problem you prioritized and why
* Who benefits from your solution
* Why AI is appropriate for the problem
* How AI changes the workflow rather than simply enhancing the interface
* Which agent, model, framework, or AI architecture you selected and why
* Where human judgment remains necessary
* How you would measure business impact
* What assumptions, risks, and tradeoffs you made
Include two or three success metrics, such as reduced triage time, fewer duplicate requests, faster prioritization, improved stakeholder response time, or higher-quality product decisions.
We are less interested in the specific feature and more interested in how thoughtfully AI is incorporated into the product or operational workflow. Your solution should clearly explain the agent or AI technology you selected and why.
Expectations
This assignment is intentionally open-ended. We are evaluating how you think about building real-world Agentic systems, not just implementing basic functionality.
You are encouraged to extend the system with additional functionality, features, and technical considerations you believe are necessary to make this a production-ready and polished product.
Submitting Your Work
The project should take roughly 2-3 hours. Please complete within 2 business days, send the following to: andres.saldarriaga@metacto.com, jamie@metacto.com
1. Push your code to GitHub; make sure the repository is public
2. Share the repository URL
3. Record a ~5 minute Loom video walking through your locally running project: product overview; features implemented; AI-powered capability; architecture decisions & technical tradeoffs; how AI was used throughout the development process
4. Include the Loom link in your submission
