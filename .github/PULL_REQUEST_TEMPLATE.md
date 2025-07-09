<!-- .github/PULL_REQUEST_TEMPLATE.md -->
<!-- This template is for the Simplicity Indexer project. Please follow all instructions to ensure a smooth review process. -->
## Description

<!-- Provide a brief description of the changes in this PR -->

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Performance improvement (change that improves performance)
- [ ] Documentation update (changes to documentation only)
- [ ] Code refactoring (no functional changes)
- [ ] Test improvements (adding or improving tests)

## Related Issue

<!-- Link to the issue this PR addresses -->
Fixes #(issue number)

## Changes Made

<!-- List the specific changes made in this PR -->
- [ ] Change 1
- [ ] Change 2
- [ ] Change 3

## Testing

### Test Coverage
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Performance tests passed
- [ ] Manual testing completed

### Test Commands
```bash
# Commands used to test the changes
pipenv run pytest tests/test_your_changes.py -v
pipenv run pytest tests/test_performance.py -v
```

### Test Results
<!-- Provide test results, especially for performance tests -->
- Unit tests: ✅ All passing
- Integration tests: ✅ All passing
- Performance tests: ✅ Response times < 20ms
- Manual testing: ✅ Functionality verified

## Performance Impact

<!-- Describe any performance implications -->
- **Response Time**: No impact / Improved by X ms / Degraded by X ms
- **Memory Usage**: No impact / Reduced by X MB / Increased by X MB
- **Database Performance**: No impact / Improved / Requires optimization
- **Cache Performance**: No impact / Improved hit rate / Requires adjustment

### Performance Test Results
```
Before: Average response time 15ms
After:  Average response time 12ms
Improvement: 3ms (20% faster)
```

## Security Considerations

<!-- Describe any security implications -->
- [ ] Input validation added/updated
- [ ] SQL injection prevention verified
- [ ] Error handling doesn't expose sensitive data
- [ ] Logging doesn't contain sensitive information
- [ ] Authentication/authorization not affected

## Breaking Changes

<!-- List any breaking changes and provide migration guidance -->
- [ ] No breaking changes
- [ ] Breaking changes listed below with migration path

### Breaking Change Details
<!-- If applicable, describe breaking changes -->
- **Change**: Description of what changed
- **Impact**: Who/what is affected
- **Migration**: How to migrate existing code

## Documentation

- [ ] README updated (if needed)
- [ ] API documentation updated
- [ ] Code comments added/updated
- [ ] Configuration documentation updated
- [ ] Docker/deployment docs updated

## Code Quality

### Pre-commit Checks
- [ ] Code formatted with black
- [ ] Linting passed (flake8)
- [ ] Type checking passed (mypy)
- [ ] Security scanning passed (bandit)
- [ ] Import sorting correct (isort)

### Code Review Checklist
- [ ] Code follows project patterns
- [ ] Functions have appropriate type hints
- [ ] Error handling is comprehensive
- [ ] Logging is appropriate
- [ ] No hardcoded values
- [ ] Code is DRY (Don't Repeat Yourself)

## Database Changes

<!-- If applicable, describe database changes -->
- [ ] No database changes
- [ ] Database schema changes (migration required)
- [ ] Database query optimization
- [ ] Index changes

### Migration Details
<!-- If database changes are made -->
- **Migration File**: `versions/xxx_description.py`
- **Migration Type**: Schema change / Data migration / Index addition
- **Backwards Compatible**: Yes / No

## Deployment

- [ ] No deployment changes required
- [ ] Environment variables added/changed
- [ ] Docker configuration updated
- [ ] Dependencies added/updated

### Environment Changes
<!-- List any new environment variables -->
```bash
# New environment variables
NEW_VARIABLE=default_value
MODIFIED_VARIABLE=new_default_value
```

## Monitoring

- [ ] No monitoring changes
- [ ] New metrics added
- [ ] Health checks updated
- [ ] Logging enhanced

## Checklist

### Developer Checklist
- [ ] I have performed a self-review of my code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] Any dependent changes have been merged and published

### Maintainer Checklist
- [ ] Code review completed
- [ ] Performance impact assessed
- [ ] Security implications reviewed
- [ ] Documentation accuracy verified
- [ ] CI/CD pipeline passed
- [ ] Breaking changes documented
- [ ] Ready for merge

## Screenshots/Demo

<!-- If applicable, add screenshots or demo links -->
<!-- For UI changes, API changes, or new features -->

## Additional Notes

<!-- Any additional information that reviewers should know -->

---

**Review Guidelines:**
- Focus on functionality, performance, and security
- Ensure tests are comprehensive
- Verify documentation is updated
- Check for potential breaking changes
- Validate performance requirements are met 