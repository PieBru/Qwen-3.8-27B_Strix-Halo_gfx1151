import re
import sys
import argparse

def minify_jinja(content):
    """
    Minifies a Jinja2 template by removing comments and collapsing whitespace.
    
    This function is designed to be "safe" for chat templates:
    1. It removes all Jinja2 comments.
    2. It replaces newlines with spaces to ensure words don't merge (e.g., "Hello\nWorld" -> "Hello World").
    3. It collapses multiple spaces into one to keep the file size small.
    4. It removes spaces between adjacent tags, as the template's use of 
       white-space stripping markers (e.g., '{%-') ensures this is safe.
    
    Args:
        content (str): The raw Jinja2 template content.
        
    Returns:
        str: The minified, single-line template.
    """
    # Remove Jinja2 comments: {# ... #}
    content = re.sub(r'\{#.*?#\}', '', content, flags=re.DOTALL)
    
    # Replace newlines and tabs with spaces. This is a "safe" minification 
    # strategy that prevents content from merging incorrectly.
    content = content.replace('\n', ' ').replace('\t', ' ')
    
    # Collapse multiple spaces into a single space.
    content = re.sub(r' +', ' ', content)
    
    # Remove spaces between Jinja tags. This is generally safe in templates 
    # that use white-space stripping (the '-' in '{%-') and significantly
    # reduces the token count for the tokenizer_config.json.
    content = content.replace('%} {%', '%}{%').replace('%} {{', '%}{{')
    content = content.replace('}} {%', '}}{%').replace('}} {{', '}}{{')
    
    return content.strip()

def main():
    # Setup argument parser for a better command-line interface
    parser = argparse.ArgumentParser(
        description="Minify a Jinja2 chat template for use in tokenizer_config.json"
    )
    parser.add_argument("input", help="Path to the source .jinja file")
    parser.add_argument("output", help="Path to save the minified output")
    
    args = parser.parse_args()
    
    try:
        # Read the input template
        with open(args.input, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Perform minification
        minified = minify_jinja(content)
        
        # Write the result to the output file
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(minified)
            
        # Provide feedback on the process
        print(f"Minification complete: '{args.input}' -> '{args.output}'")
        print(f"Original size: {len(content)} bytes")
        print(f"Minified size: {len(minified)} bytes")
        print(f"Reduction: {100 - (len(minified) / len(content) * 100):.1f}%")
        
    except FileNotFoundError:
        print(f"Error: The file '{args.input}' was not found.")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
